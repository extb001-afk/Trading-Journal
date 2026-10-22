'use strict';
(window.__tjTabs = window.__tjTabs || {}).dash = function (X) {
  const {
    $, ago, arr, bfInfo, CH_RANGES, CHAIN_KEY, clps, cls, clsP, clsV, dayCnt, dayFlowV, dayFull, dayV, DOWS, drawerHist, eok, esc, evA, evQ, evXf,
    EX_BY_KO, EX_NAMES, exLogo, fmtTs, futFxNote, hq, hs, IC, icon, impChip, isDex, isISO, isoDay, isYMD, isZ, krw, KS, KV, LS, m, mN, N, nbDot, nf,
    num, onUnauthorized, openDay, pad2, pAgg, partHave, partsNeed, PCAT_ORDER, PCATS, pctS, plPx, prTxt, PVM, pvm, pvW, px, pxC, pxSrcTxt, q, rate,
    rbChip, renderAuto, renderOverlay, renderView, retPct, revealAndHighlight, rw, S, scanText, short, staleChip, sum, toast, todayISO, trimZeros,
    UI_SHEETS, uiCell, uiFold, uiPaged, uiPgBar, uiPgS, uiPgSlice, uiPgSz, uiSheetCloseThen, uiSheetOpen, venueLogo, wowSlot, ymOf, ymShift
  } = X;
  let A, apOf, copyBtn, dayContrib, evPill, EXPL, feeRef, groupDayEvs, isoAdd, levHTML, locH, locName, mAlt, monthAtt, monthBarRows, nmKey, oaDashLine, openFutRcpt, realDays, suSt, sxKeys, topRcptSym, trChip, vib;
  const __late = L => {
    if ('A' in L) A = L.A;
    if ('apOf' in L) apOf = L.apOf;
    if ('copyBtn' in L) copyBtn = L.copyBtn;
    if ('dayContrib' in L) dayContrib = L.dayContrib;
    if ('evPill' in L) evPill = L.evPill;
    if ('EXPL' in L) EXPL = L.EXPL;
    if ('feeRef' in L) feeRef = L.feeRef;
    if ('groupDayEvs' in L) groupDayEvs = L.groupDayEvs;
    if ('isoAdd' in L) isoAdd = L.isoAdd;
    if ('levHTML' in L) levHTML = L.levHTML;
    if ('locH' in L) locH = L.locH;
    if ('locName' in L) locName = L.locName;
    if ('mAlt' in L) mAlt = L.mAlt;
    if ('monthAtt' in L) monthAtt = L.monthAtt;
    if ('monthBarRows' in L) monthBarRows = L.monthBarRows;
    if ('nmKey' in L) nmKey = L.nmKey;
    if ('oaDashLine' in L) oaDashLine = L.oaDashLine;
    if ('openFutRcpt' in L) openFutRcpt = L.openFutRcpt;
    if ('realDays' in L) realDays = L.realDays;
    if ('suSt' in L) suSt = L.suSt;
    if ('sxKeys' in L) sxKeys = L.sxKeys;
    if ('topRcptSym' in L) topRcptSym = L.topRcptSym;
    if ('trChip' in L) trChip = L.trChip;
    if ('vib' in L) vib = L.vib;
  };
  function gMatch(g, sym, pkey) {
    const pk = String(pkey || '').replace(/f\d+$/, '');
    if (g.key.charAt(0) === '#') return pk === g.key.slice(1);
    const pg = S.D.posGrp && S.D.posGrp[String(pkey || '')];
    if (pg) return pg === g.key;
    if (g.key.indexOf('~') > 0) return g.keys.indexOf(pk) >= 0;
    return String(sym).toUpperCase() === g.key && !(g.twin && S.D.groups.some(x => x !== g && x.key.indexOf(g.key + '~') === 0 && x.keys.indexOf(pk) >= 0));
  }
  function dustOk(v) { return S.hold.showDust || S.dust <= 0 || Math.abs(v) >= S.dust; }
  function monthRealized(ym) {
    ym = ym || ymShift(0);
    const ks = Object.keys(S.D.realized).filter(k => k.slice(0, 3) === ym.slice(5, 7) + '-' && ymOf(k) === ym);
    return KV(sum(ks, k => num(S.D.realized[k])), S.D.hasKrw ? sum(ks, k => num(S.D.realizedK[k])) : null);
  }
  function onbState() {
    const st = suSt(), D = S.D;
    if (!st || st.demo || !D) return null;
    const wl = arr(st.wallets).length, bf = bfInfo(), pre = preData();
    if (!(wl === 0 || pre || (!st.onboarded && bf && !arr(D.events).length))) return null;
    const solW = arr(st.wallets).some(w => w && w.kind === 'sol'), solNeed = !!st.solNeedsHelius && solW;
    const K = sxKeys(), xp = st.explorers || {}, needX = !!(st.evmNeedsKeys || st.evmNeedsAlchemy || st.evmNeedsAnkr || solNeed);
    const miss = [st.evmNeedsKeys && !(xp.etherscan || {}).set ? 'Etherscan' : '', st.evmNeedsAlchemy && xp.alchemy && !xp.alchemy.set ? 'Alchemy' : '', st.evmNeedsAnkr && xp.ankr && !xp.ankr.set ? 'Ankr' : '', solNeed && !(xp.helius || {}).set ? 'Helius' : ''].filter(Boolean);
    return { wl, bf, pre, K, needX, miss, tg: !!(st.telegram && st.telegram.connected) };
  }
  const ONB_X = 'tj_v2_onbx';
  const onbHidden = () => LS.get(ONB_X) === '1';
  function onbHTML() {
    const o = onbHidden() ? null : onbState();
    if (!o) return '';
    const K = o.K || { xs: 0, xn: 0, es: 0, en: 0, empty: [] };
    const row = (ok, opt, t, d, st) => '<li class="' + (ok ? 'o-ok' : opt ? 'o-opt' : st ? 'o-wait' : 'o-need') + '"><span class="oi" aria-hidden="true">' + (ok ? IC.check.replace('<svg', '<svg width="14" height="14"') : '') + '</span><span class="ot"><b>' + t + '</b><span class="cap">' + d + '</span></span><span class="os">' + (ok ? '완료' : opt ? '선택' : st || '해야 해요') + '</span></li>';
    const collect = !o.wl ? '지갑을 넣으면 수집기가 과거 거래(최근 몇 달)부터 불러와요'
      : o.bf ? '옛 기록 불러오는 중 <b class="num">' + o.bf.pct + '%</b>' + (o.bf.stalled ? ' · 멈춤 — 설정 › 상태에서 확인해요' : '') : o.pre ? '수집기가 첫 수집을 시작하길 기다리는 중이에요' : '첫 수집이 끝났어요';
    return '<section class="card onb" aria-label="처음 설정" data-su-scope><div class="th"><h2>처음 설정 · 첫 수집</h2><span class="cap">첫 수집이 끝날 때까지 여기 있어요 — ' + (S.D && S.D.prov ? '보유·총자산은 지금 실제 잔고로 보여요 · 원가·손익·지난날 곡선은 옛 기록을 다 받으면 정확하게 맞춰져요' : '그 전엔 금액이 <span class="pvx">₩0</span> 으로 보여요') + '</span></div>'
      + '<ol class="onbl">'
      + row(o.wl > 0, false, '지갑 등록', o.wl ? '<span class="pvx">' + o.wl + '개</span> 등록됨' : '조회할 지갑 주소를 넣어요(키·시드는 받지 않아요)')
      + row(o.needX ? !o.miss.length : K.xs > 0, !o.needX, '탐색기 키', o.miss.length ? esc(o.miss.join('·')) + ' 키가 있어야 지갑 체인을 읽어요' : K.xn ? K.xs + ' / ' + K.xn + '개 넣음' : '—')
      + row(K.es > 0, true, '거래소 연결', K.es ? K.es + '곳 연결됨' : '조회 전용 키 — 없으면 지갑만 집계해요')
      + row(o.tg, true, '텔레그램 알림', o.tg ? '연결됨' : '큰 입출금·청산 위험을 알려 줘요')
      + row(!o.pre && !o.bf && o.wl > 0, false, '첫 수집', collect, o.wl ? '진행 중' : '지갑 먼저')
      + '</ol><div class="onbf"><button class="btn pri sm" data-su="wizard">설정 이어서 하기</button><span class="cap">설정 › 연결·키에서도 언제든 바꿀 수 있어요</span>'
      + (o.bf && !o.bf.stalled ? '' : '<span class="sp"></span><button type="button" class="btn sm" data-a="onbClose" title="이 기기에서 안내 카드를 숨겨요 — 설정 › 연결·키에서 다시 볼 수 있어요">닫기</button>') + '</div></section>';
  }
  function vDash() {
    const sideFL = !S.mobile && !S.narrow;
    return onbHTML() + heroHTML() + allocHTML()
      + '<div class="grid2"><div style="display:flex;flex-direction:column;gap:20px;min-width:0">' + holdingsHTML() + (sideFL ? '' : futPosHTML()) + '</div>'
      + '<div class="side' + (S.sideFit ? ' sfit' : '') + '" data-ks="side">' + venuesHTML() + cashHTML() + (sideFL ? futPosHTML(true) : '') + watchHTML() + '</div></div>';
  }
  function histLoad() {
    const H = S.hist, ver = S.ver;
    if (H.st === 'none' || H.st === 'loading' || (H.ver === ver && (H.st === 'ok' || H.st === 'err'))) return;
    H.st = 'loading';
    fetch('/api/curve_hist?range=all', { cache: 'no-store' }).then(r => {
      if (r.status === 404) { H.st = 'none'; H.days = []; if (S.chartDays > 30) S.chartDays = 30; return null; }
      if (!r.ok && r.status !== 202) throw new Error('HTTP ' + r.status);
      return r.json().then(j => {
        H.days = arr(j && j.days).filter(x => Array.isArray(x) && isISO(x[0]) && x[1] != null && isFinite(+x[1]));
        H.building = !!(j && j.building); H.flowBuilding = !!(j && j.flowBuilding); H.prog = (j && j.progress) || null; H.st = 'ok'; H.ver = ver;
      });
    }).catch(() => { H.st = 'err'; H.ver = ver; }).then(() => { if (S.D && S.tab === 'dash') renderAuto(); });
  }
  function chartData() {
    const D = S.D;
    const long = S.chartDays > 30;
    const src = long ? D.daily.slice() : D.daily.slice(-S.chartDays);
    if (!src.length) return null;
    let pts = src.map(x => ({ date: x.date, dow: x.dow, val: dayV(x), delta: x._prev ? dayV(x) - dayV(x._prev) : null, ap: num(x.ap), row: x }));
    if (pts[pts.length - 1].date === D.todayKey) { const l = pts[pts.length - 1]; l.val = D.total; l.ap = 0; l.delta = l.row._prev ? l.val - dayV(l.row._prev) : null; }
    if (long) {
      if (S.hist.ver !== S.ver) histLoad();
      const f0 = isoDay(src[0].date) || '', lo = S.chartDays >= 9999 ? '' : isoAdd(todayISO(), -(S.chartDays - 1));
      const old = arr(S.hist.days).filter(x => x[0] < f0 && x[0] >= lo).map(x => {
        const row = { date: x[0], val: num(x[1]), valKrw: x[2] != null && isFinite(+x[2]) ? num(x[2]) : null, _hist: 1 };
        if (x[5] != null && isFinite(+x[5])) { row.flow = num(x[5]); if (num(x[6]) > 0) row.usdt = num(x[6]); if (Array.isArray(x[7])) row.flowTop = x[7]; }
        if (x[8] != null && isFinite(+x[8]) && num(x[8]) !== 0) row.nofx = num(x[8]);
        return { date: x[0], dow: DOWS[new Date(x[0] + 'T00:00:00').getDay()], val: dayV(row), delta: null, ap: num(x[3]) > 0 ? Math.max(1, num(x[4])) : 0, row };
      });
      old.forEach((p, i) => { if (i) p.delta = p.val - old[i - 1].val; });
      old.forEach((p, i) => { if (i && p.row.flow != null) { const dU = p.row.val - old[i - 1].row.val; p.row.split = D.flowBig(p.row.flow, old[i - 1].row.val) || D.flowSplitOk(p.row.flow, dU); } });
      if (old.length && pts[0].delta == null) pts[0].delta = pts[0].val - old[old.length - 1].val;
      pts = old.concat(pts);
    }
    return pts;
  }
  function todayD() { const D = S.D; return D && D._today != null ? D.total - dayV(D._pv) : null; }
  function heroNums() {
    const D = S.D;
    const pts = chartData();
    const prev = D.daily.length > 1 && D.daily[D.daily.length - 1].date === D.todayKey ? D.daily[D.daily.length - 2] : D.daily[D.daily.length - 1];
    const pvV = prev ? dayV(prev) : null;
    const today = prev ? D.total - pvV : null;
    const todayPct = prev && pvV ? today / pvV * 100 : null;
    const first = pts && pts[0];
    let rng = first ? D.total - first.val : null;
    const steps = pts ? pts.filter((p, i) => i > 0 && D.steps.indexOf(p.date) >= 0) : [];
    const stepSum = D.hasFlow ? sum(pts ? pts.slice(1) : [], p => p.date === D.todayKey ? num(D._todayFlow) : num(dayFlowV(p.row))) : sum(steps, p => num(p.delta));
    const adj = rng != null ? rng - stepSum : null;
    const histFlowMiss = !!(pts && pts.some((p, i) => i > 0 && p.row && p.row._hist && p.row.flow == null));
    const nofxPts = pts ? pts.filter((p, i) => i > 0 && p.row && p.row._hist && p.row.nofx) : [];
    return { pts, prev, today, todayPct, first, rng, adj, steps, disc: !!D._todayStep, split: !!D._todaySplit, flow: D._todayFlow, ap: D._todayAp,
      hist: !!(pts && pts.some(p => p.row && p.row._hist)), histFlowMiss, flowSum: stepSum, nofxN: nofxPts.length, nofxK: sum(nofxPts, p => num(p.row.nofx)) };
  }
  function flowTip(fl, top) { return '입출금 ' + m(num(fl), { sign: true }) + (arr(top).length ? ' — ' + arr(top).map(t => t[0] + ' ' + m(num(t[1]), { sign: true, compact: true })).join(' · ') : '') + ' · 입출금 = 외부·원화 입출금 + 거래소 잔고 정정·원가 없는 유입(시세 변동 아님)'; }
  function flowSplit(delta, fl, top, lead) { return '<span class="nw">' + (lead ? '· ' : '') + '시장 변동 <span class="' + cls(delta - num(fl)) + '">' + m(delta - num(fl), { sign: true, compact: true }) + '</span></span> <span class="nw" title="' + esc(flowTip(fl, top)) + '">· 입출금 ' + m(num(fl), { sign: true, compact: true }) + '</span>'; }
  function attOf(k) {
    const D = S.D, x = D && D.dayMap.get(k);
    if (!x || !x.att || typeof x.att !== 'object' || !x._prev) return null;
    const a = x.att, isT = k === D.todayKey;
    const delta = isT ? todayD() : dayV(x) - dayV(x._prev);
    if (delta == null || !isFinite(delta)) return null;
    const krw = S.cur !== 'USD';
    const kf = krw && !isT && x.valKrw != null && num(x.usdt) > 0 ? num(x.usdt) / rate() : 1;
    const kx = num(a.kx) * kf;
    const tx = attTx(a.topx, kf);
    const top = arr(a.top).map(t => ({ sym: String(t[0]), pct: t[1] == null ? null : num(t[1]), v: num(t[2]) * kf, x: tx[String(t[0])] || null }));
    const etc = { n: num((a.etc || [])[0]), v: num((a.etc || [])[1]) * kf };
    const fx = krw ? num(x._prev.val) * kf - dayV(x._prev) + kx : 0;
    const fl = isT ? num(D._todayFlow) : num(dayFlowV(x));
    const ap = isT ? !!D._todayAp : (apOf(x) || apOf(x._prev));
    const unp = a.unp ? { n: num(a.unp[0]), v: num(a.unp[1]) * kf } : null;
    if (a.rz != null && a.ev != null) {
      const ev = num(a.ev) * kf, xm = num(a.xm) * kf, gx = num(a.gx) * kf, ur = (num(a.ur) - num(a.gx)) * kf;
      const hold = (num(a.ev) - num(a.xm) - num(a.ur)) * kf;
      const rz = num(a.rz) * kf, lpf = num(a.lpf) * kf, un = num(a.un) * kf;
      const fxl = krw ? fx : kx;
      const mvd = ur * rz < 0 ? ur : 0;
      const stk = num(a.stk) * kf;
      const iso9 = isoDay(k), fF = D.f || {}, fU = D.fut || {};
      const at9 = mp => (mp && mp[iso9] != null ? mp[iso9] : mp ? mp[k] : null);
      const kvP = (u, kr) => KV(u, D.hasKrw ? (kr != null && isFinite(kr) ? num(kr) : u * rate()) : null);
      const rzS = kvP(num(at9(fF.realizedByDate)), at9(fF.realizedKrwByDate));
      const rzF = kvP(num(at9(fU.realizedByDate)), at9(fU.realizedKrwByDate));
      const fbU = num(a.fb), fb = fbU * kf, foU = fbU - num(at9(fU.realizedByDate));
      const flC = fl - stk, fo = Math.abs(foU) < 0.015 ? 0 : (fbU ? foU * kf : -rzF);
      const fxC = fxl + (rz + lpf + fl + fb) - (rzS + rzF + flC + fo);
      const op = num(a.op) * kf;
      return { v2: true, k, isT, delta, mk: ev, hold, xm, ur, gx, rz: rzS, rzf: rzF, fo, fb, rz0: rz, lpf, stk, un, op, mvd, top, etc, kx: 0, fx: fxC, fl: flC, fl0: fl, tr: 0, fee: num(a.fee) * kf,
        oth: delta - ev - rz - lpf - fl - fxl - un - fb - op, np: num(a.np), unp, ap,
        xr: num(a.xr) * kf, xca: !!a.xca, rbv: num(a.rbv) * kf };
    }
    const mk = num(a.mk) * kf - (krw ? kx : 0);
    const tr = num(a.tr) * kf;
    return { delta, mk, top, etc, kx: krw ? 0 : kx, fx, fl, tr, fee: num(a.fee) * kf, lp: num(a.lp) * kf, xo: num(a.xo) * kf,
      oth: delta - mk - fx - fl - tr, unp, ap };
  }
  function attTx(list, kf) {
    const out = {};
    const one = (x, o) => {
      const p0 = num(x.p0), p1 = num(x.p1), q0 = num(x.q);
      if (!(p0 > 0) || !(p1 > 0) || !isFinite(q0) || !isFinite(p0) || !isFinite(p1)) return null;
      return Object.assign(o || {}, { q: q0, p0, p1, k: x.k == null ? null : String(x.k), k0: x.k0 == null ? null : String(x.k0),
        src: x.src ? String(x.src) : '', src0: x.src0 ? String(x.src0) : '', spike: x.flag === 'spike', fr: String(x.fr || ''), rx: num(x.rx) });
    };
    arr(list).forEach(x => {
      if (!x || typeof x !== 'object' || x.sym == null) return;
      const o = one(x);
      if (!o) return;
      o.gn = num(x.gn);
      o.gs = arr(x.gs).map(g => (g && typeof g === 'object' ? one(g, { v: num(g.usd) * kf }) : null)).filter(Boolean);
      out[String(x.sym)] = o;
    });
    return out;
  }
  const attSig = (a, v) => Math.abs(v) >= Math.max(1, 0.01 * Math.abs(a.delta));
  const ATT_IT1 = [['fl', '입출금'], ['tr', '매매'], ['fx', '환율']];
  const ATT_IT2 = [['rz', '현물 실현'], ['rzf', '선물 실현'], ['fl', '입출금'], ['fx', '환율'], ['fo', '선물 미반영'], ['un', '원가 미확인'], ['op', '기초 잔고 정정']];
  function attItems(a) {
    const out = [];
    let rest = a.oth;
    const KEEP9 = { rz: 1, rzf: 1, fo: 1 };
    (a.v2 ? ATT_IT2 : ATT_IT1).forEach(p => { const v9 = a[p[0]]; if (attSig(a, v9) || (KEEP9[p[0]] && Math.abs(num(v9)) >= 0.005)) out.push([p[1], v9]); else rest += num(v9); });
    const R = S.cur === 'USD' ? 1 : rate(), w = Math.abs(a.delta) * R;
    const unit = S.cur === 'USD' ? (w >= 1e6 ? 1e4 : w >= 1e4 ? 100 : w >= 100 ? 1 : 0.01) : (w >= 1e8 ? 1e6 : w >= 1e4 ? 1e4 : 1);
    if (Math.abs(rest) * R >= unit / 2) out.push(['나머지', rest]);
    return out;
  }
  function attItemsK(a) {
    const its = attItems(a), L = a.v2 ? ATT_IT2 : ATT_IT1, shown = new Set(its.map(x => x[0]));
    const fold = L.filter(p => !shown.has(p[1]) && num(a[p[0]])).map(p => p[0]);
    return its.map(x => { const p = L.find(q => q[1] === x[0]); return { key: p ? p[0] : 'oth', l: x[0], v: x[1], fold: p ? [] : fold }; });
  }
  const attMvd = a => !!(a && a.v2 && a.mvd && attSig(a, a.mvd) && attSig(a, a.rz));
  const ATT_MVD_TIP = '그날 사고판 코인의 평가 차 — 판 코인에 쌓여 있던 평가 손익이 팔면서 시세 변동에서 빠져 실현 줄로 옮겨간 몫이 들어 있어요(그날 산 코인의 마감까지 평가 변화도 함께)';
  function attMovers(a, n, html) {
    const shown = a.top.slice(0, n).filter(t => Math.abs(t.v) >= 0.005), mv = attMvd(a) ? a.mvd : 0, rest = a.mk - sum(shown, t => t.v) - mv;
    const V = v => html ? '<span class="' + cls(v) + '">' + m(v, { sign: true, compact: true }) + '</span>' : m(v, { sign: true, compact: true });
    const one = t => esc(t.sym) + (t.pct != null ? ' ' + pctS(t.pct, 1) : '') + ' ' + V(t.v);
    const bits = shown.map(one);
    const mvB = '<button type="button" class="amvd" data-a="attdOpen" data-v="' + esc('d|' + a.k + '|ur') + '" aria-haspopup="dialog"';
    if (mv) bits.push(html ? mvB + ' title="' + esc(ATT_MVD_TIP) + '">사고판 분(→실현) ' + V(mv) + '</button>' : '사고판 분(→실현) ' + V(mv));
    if (bits.length && Math.abs(rest) >= 0.5) bits.push('기타 ' + m(rest, { sign: true, compact: true }));
    if (html) return bits.map((x, i) => '<span class="nw">' + (i ? '· ' : '') + x + '</span>').join(' ');
    return bits.join(' · ');
  }
  function attLine(a, n, html) {
    const V = v => html ? '<span class="' + cls(v) + '">' + m(v, { sign: true, compact: true }) + '</span>' : m(v, { sign: true, compact: true });
    const mv = attMovers(a, n, html);
    const bits = ['시세 ' + V(a.mk) + (mv ? ' (' + mv + ')' : '')].concat(attItems(a).map(x => x[0] + ' ' + V(x[1])));
    if (html) return (a.ap ? '≈ ' : '') + bits.map((x, i) => i ? '<span class="nw">· ' + x + '</span>' : x).join(' ');
    return (a.ap ? '≈ ' : '') + bits.join(' · ');
  }
  const josa = (w, a, b) => { const c = String(w).charCodeAt(String(w).length - 1); return c >= 0xAC00 && c <= 0xD7A3 && (c - 0xAC00) % 28 === 0 ? b : a; };
  function attCore(a) {
    const it0 = [['시세', a.mk]].concat(attItems(a)), fpair = it0.some(x => x[0] === '선물 실현') && it0.some(x => x[0] === '선물 미반영');
    const fnet = fpair ? num(a.rzf) + num(a.fo) : 0;
    const it = it0.filter(x => !(fpair && (x[0] === '선물 실현' || x[0] === '선물 미반영'))).concat(fpair ? [['선물 실현', fnet]] : [])
      .filter(x => Math.abs(num(x[1])) >= 0.5).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
    const tot = sum(it, x => Math.abs(num(x[1])));
    if (!it.length || !(tot > 0)) return '';
    const w = x => x[0] === '시세' ? (x[1] < 0 ? '시세 하락' : '시세 상승') : x[0] === '입출금' ? (x[1] < 0 ? '출금' : '입금')
      : x[0] === '환율' ? (x[1] < 0 ? '환율 하락' : '환율 상승') : x[0] === '매매' ? '매매 체결 차'
      : x[0] === '실현' || x[0] === '현물 실현' ? '실현 손익' : x[0] === '선물 실현' ? '선물 정산' : x[0] === '선물 미반영' ? '총자산에 안 든 선물 정산'
      : x[0] === 'LP 수수료' ? 'LP 수수료' : x[0] === '원가 미확인' ? '원가 모르는 매도' : x[0] === '기초 잔고 정정' ? '기초 잔고 정정' : '그 밖 요인';
    const w0 = w(it[0]);
    if (Math.abs(it[0][1]) / tot >= 0.5 || it.length < 2) return '총자산 변동은 ' + w0 + josa(w0, '이', '가') + ' 대부분이다.';
    const w1 = w(it[1]);
    return '총자산 변동은 ' + w0 + josa(w0, '과', '와') + ' ' + w1 + josa(w1, '이', '가') + ' 컸다.';
  }
  function attDetail(a, k, noCoins) {
    const D = S.D, x = D.dayMap.get(k) || {};
    const row = (l, v, sub) => '<div class="ar"><span class="al">' + l + '</span><b class="num ' + cls(v) + '">' + m(v, { sign: true, compact: true }) + '</b>' + (sub ? '<span class="as">' + sub + '</span>' : '') + '</div>';
    const srow = (l, v, at) => '<' + (at ? 'button type="button" ' + at : 'div') + ' class="ar sub"><span class="al mut">' + l + '</span><span></span><b class="num ' + cls(v) + '">' + m(v, { sign: true, compact: true }) + '</b></' + (at ? 'button' : 'div') + '>';
    const mx = Math.max.apply(null, a.top.map(t => Math.abs(t.v)).concat([1e-9]));
    const coins = noCoins ? '' : a.top.map(t => '<div class="ar sub"><span class="al">' + icon(t.sym, 'xs', D.symLogo[t.sym.toUpperCase()] || {}) + esc(t.sym) + (t.pct != null ? ' <span class="mut">' + pctS(t.pct, 2) + '</span>' : '') + '</span><span class="cb2"><i class="' + (t.v >= 0 ? 'p' : 'n') + '" style="width:' + Math.max(3, Math.abs(t.v) / mx * 100).toFixed(1) + '%"></i></span><b class="num ' + cls(t.v) + '">' + m(t.v, { sign: true, compact: true }) + '</b></div>').join('')
      + (a.etc.n && !noCoins ? srow('기타 ' + a.etc.n + '종', a.etc.v) : '');
    const ft = k === D.todayKey ? D._todayFlowTop : x.flowTop;
    const flSub = arr(ft).length ? esc(arr(ft).map(t => t[0]).join(' · ')) : '외부 입출금·원화 입출금·거래소 잔고 정정';
    if (a.v2) {
      const big = v => Math.abs(v) >= 0.5;
      let h = '<div class="attd">' + row('시세 (평가)', a.mk, '전일 보유 코인 × 가격 변화(그날 마감가) + 원장 밖 코인 + 그날 사고판 분 — 팔아서 확정된 몫은 아래 실현에')
        + coins
        + (big(a.xm) ? srow('원장 밖 코인(업비트 미매칭)', a.xm) : '')
        + (big(a.ur) ? srow('그날 사고판 분', a.ur, 'data-a="attdOpen" data-v="' + esc('d|' + k + '|ur') + '" aria-haspopup="dialog"') : '')
        + (big(a.gx) ? srow('같은 코인 가격 묶음 차', a.gx) : '');
      if (attMvd(a)) h += '<div class="ar sub amvdn"><span class="as">그날 사고판 분 ' + m(a.mvd, { sign: true, compact: true }) + ' — 판 코인에 쌓여 있던 평가 ' + (a.mvd < 0 ? '이익' : '손실') + '이 팔면서 시세에서 ' + (a.mvd < 0 ? '빠지고' : '더해지고') + ' 실현 줄로 옮겨간 몫이 들어 있어요(그날 산 코인의 마감까지 평가 변화 포함 · 자리만 옮긴 돈)</span></div>';
      else if (big(a.ur)) h += '<div class="ar sub amvdn"><span class="as">그날 사고판 분 = 판 코인의 평가 손익이 실현으로 옮겨가며 빠지는 몫 + 그날 산 코인의 마감까지 평가 변화</span></div>';
      const inc = [big(a.lpf) ? 'LP 수수료 ' + m(a.lpf, { sign: true, compact: true }) : '', big(a.stk) ? '스테이킹 보상 ' + m(a.stk, { sign: true, compact: true }) : ''].filter(Boolean);
      h += row('현물 실현', a.rz, '그날 판 것의 원가 대비 손익' + (inc.length ? '(' + inc.join(' · ') + ' 포함)' : '') + ' — 위 칸 총 실현의 현물 몫');
      if (big(a.rzf) || big(a.fo)) h += row('선물 실현', a.rzf, '그날 선물 정산(정산 + 수수료 + 펀딩) — 위 칸 총 실현의 선물 몫');
      h += row('입출금', a.fl, flSub + (big(a.stk) ? ' · 스테이킹 보상은 현물 실현에' : ''));
      if (big(a.fx)) h += row('환율', a.fx, S.cur === 'USD' ? '원화 예수금의 달러 환산(그날 USDT 종가 차)' : '달러 자산의 원화 환산(그날 USDT 종가 차) · 원화 예수금 포함 · 실현을 체결 시각 환율로 센 차');
      if (big(a.fo)) h += row('선물 미반영', a.fo, '그날 총자산 변화에 아직 안 든 선물 정산 — 선물 지갑 잔고는 거래소 잔고 대사(약 10분마다)가 정산 시각에 넣어요. 마지막 대사 뒤 정산이거나, 예전 방식이 지난날로 넣은 몫이에요. 줄 합을 전일 대비와 맞추려고 빼요');
      if (big(a.un)) h += row('원가 미확인', a.un, '원가를 모르는 코인을 판 금액 − 그날 가격 평가 — 실현·평가로 못 나눠요');
      if (big(a.op)) h += row('기초 잔고 정정', a.op, '전부터 있던 보유를 이날 원장에 넣음(발견·재점검 기초 잔고 × 그날 가격) — 실제로 들어온 돈이 아니에요');
      const ob = [a.np ? '가격 못 정한 토큰 ' + a.np + '종(그 거래는 0 으로 셈)' : '',
        a.unp && big(a.unp.v) ? '가격 한쪽 없는 코인 ' + a.unp.n + '종 ' + m(a.unp.v, { sign: true, compact: true }) : '',
        big(a.xr) ? (a.xca ? '원장 밖 잔고 이월(≈)→실측 차 ' : '원장 밖 잔고(코인별 기록 없는 몫·LP) ') + m(a.xr, { sign: true, compact: true }) : '',
        big(a.rbv) ? 'Rabby 기준 보유 변화 ' + m(a.rbv, { sign: true, compact: true }) : '',
        a.isT ? '오늘은 실시간 값과 마지막 분해 시각 차' : ''].filter(Boolean);
      h += row('나머지', a.oth, (ob.length ? ob.join(' · ') + ' · ' : '') + '원장 밖 잔고 수량 변화 · 마감 스냅샷 시각 차 · 근사·반올림' + (a.ap ? ' · 근사(≈) 날 — 시세 기록 없는 자산은 추정가라 시세 기여가 0' : ''));
      return h + '</div>';
    }
    let h = '<div class="attd">' + row('시세', a.mk, '전일 마감 수량 × 가격 변화(그날 마감가)') + coins
      + (Math.abs(a.kx) >= 0.5 ? srow('원화 예수금 달러 환산', a.kx) : '');
    h += row('입출금', a.fl, flSub);
    h += row('매매', a.tr, '마감가 대비 체결 차' + (Math.abs(a.fee) >= 0.005 ? ' · 수수료·가스 ' + m(a.fee, { sign: true, compact: true }) : ''));
    if (Math.abs(a.fx) >= 0.5) h += row('환율', a.fx, '달러 자산의 원화 환산(그날 USDT 종가 차)');
    const ob = [Math.abs(a.lp) >= 0.5 ? 'LP 예치·회수 ' + m(a.lp, { sign: true, compact: true }) : '', Math.abs(a.xo) >= 0.5 ? '원장 밖 잔고 ' + m(a.xo, { sign: true, compact: true }) : '',
      a.unp && Math.abs(a.unp.v) >= 0.5 ? '가격 한쪽 없는 코인 ' + a.unp.n + '종' : ''].filter(Boolean);
    const rest = a.oth - (Math.abs(a.lp) >= 0.5 ? a.lp : 0) - (Math.abs(a.xo) >= 0.5 ? a.xo : 0);
    if (attSig(a, rest)) ob.push('수량 되감기·근사 차 ' + m(rest, { sign: true, compact: true }));
    h += row('나머지', a.oth, (ob.length ? ob.join(' · ') + ' · ' : '') + '근사·반올림 포함' + (a.ap ? ' · 근사(≈) 날 — 시세 기록 없는 자산은 추정가라 시세 기여가 0' : ''));
    return h + '</div>';
  }
  function attHTML(k) {
    const a = attOf(k);
    if (!a) return '';
    const open = S.attOpen === k;
    return '<div class="attl cap num"><span class="attx">' + attLine(a, S.mobile ? 2 : 3, true) + '</span> <button class="link atttog" data-a="attTog" data-v="' + esc(k) + '" aria-expanded="' + open + '">' + (open ? '접기' : '자세히') + IC.chev.replace('<svg', '<svg class="cv' + (open ? ' o' : '') + '" width="13" height="13"') + '</button></div>' + (open ? attDetail(a, k) : '');
  }
  function bestDay(ym) {
    const D = S.D;
    ym = ym || ymShift(0);
    let bk = null, bv = 0;
    realDays(ym).forEach(x => { if (x.v > bv + 1e-12) { bv = x.v; bk = x.k; } });
    if (!bk) return null;
    const iso = isoDay(bk), by = new Map();
    const pick = mp => { let v = 0; Object.keys(mp || {}).forEach(x => { if (isoDay(x) === iso) v += num(mp[x]); }); return v; };
    D.merged.concat(D.lpCycles).forEach(p => { const v = pick(p.realizedByDay); if (Math.abs(v) < 0.005) return;
      const nm = p._lp ? String(p.sym).replace(/\s*\/\s*/g, '/') + ' LP' : String(p.sym); by.set(nm, num(by.get(nm)) + v); });
    const rf = pick(D.fut.realizedByDate); if (Math.abs(rf) >= 0.005) by.set('선물', num(by.get('선물')) + rf);
    let top = '', tv = 0; by.forEach((v, nm) => { if (Math.abs(v) > Math.abs(tv)) { tv = v; top = nm; } });
    return { k: bk, iso, usd: num(D.realized[bk]), v: bv, sym: top, more: by.size > 1 };
  }
  function dayRealISO() {
    const D = S.D, f = D.f || {}, out = {};
    const add = (mp, mk) => Object.keys(mp || {}).forEach(k => { const iso = isYMD(k) ? String(k).slice(0, 10) : isoDay(k); if (!iso || !isYMD(iso)) return; const e = out[iso] || (out[iso] = [0, 0]); e[0] += num(mp[k]); e[1] += mk && mk[k] != null ? num(mk[k]) : num(mp[k]) * rate(); });
    add(f.realizedByDate, f.realizedKrwByDate); add(D.fut.realizedByDate, D.fut.realizedKrwByDate);
    return out;
  }
  function bestOf(iso, v, usd) {
    const D = S.D, by = new Map();
    const pick = mp => { let x = 0; Object.keys(mp || {}).forEach(k => { if (isoDay(k) === iso) x += num(mp[k]); }); return x; };
    D.merged.concat(D.lpCycles).forEach(p => { const x = pick(p.realizedByDay); if (Math.abs(x) < 0.005) return;
      const nm = p._lp ? String(p.sym).replace(/\s*\/\s*/g, '/') + ' LP' : String(p.sym); by.set(nm, num(by.get(nm)) + x); });
    const rf = pick(D.fut.realizedByDate); if (Math.abs(rf) >= 0.005) by.set('선물', num(by.get('선물')) + rf);
    let top = '', tv = 0; by.forEach((x, nm) => { if (Math.abs(x) > Math.abs(tv)) { tv = x; top = nm; } });
    return { k: iso, iso, usd, v, sym: top, more: by.size > 1 };
  }
  function bestRange(from, to, R) {
    R = R || dayRealISO();
    let bk = null, bv = 0, bu = 0;
    Object.keys(R).sort().forEach(k => { if (k < from || k > to) return; const v = KV(R[k][0], S.D.hasKrw ? R[k][1] : null); if (v > bv + 1e-12) { bv = v; bk = k; bu = R[k][0]; } });
    return bk ? bestOf(bk, bv, bu) : null;
  }
  const addMonISO = (iso, k) => { const y = +iso.slice(0, 4), mo = +iso.slice(5, 7) - 1 + k, d = +iso.slice(8, 10), yy = y + Math.floor(mo / 12), mm = ((mo % 12) + 12) % 12, dim = new Date(yy, mm + 1, 0).getDate(); return yy + '-' + pad2(mm + 1) + '-' + pad2(Math.min(d, dim)); };
  function bestSpan() {
    const td = todayISO(), cd = S.chartDays || 30, R = dayRealISO(), ks = Object.keys(R).sort();
    const ck = cd >= 9999 ? arr(S.hist && S.hist.days).map(r => String(r[0])).concat(arr(S.D.daily).map(r => isoDay(r.date) || String(r.date))).filter(k => isYMD(k) && k <= td).sort() : [];
    const from = cd >= 9999 ? ([ck[0], ks[0]].filter(Boolean).sort()[0] || td) : isoAdd(td, -(cd - 1));
    let nWin = cd <= 30 ? 1 : cd >= 9999 ? 1 : Math.round(cd / 30.4);
    if (cd >= 9999) while (addMonISO(td, -nWin) >= from) nWin++;
    return { from, to: td, nWin, R, cd };
  }
  function bestWindows() {
    const sp = bestSpan(), out = [];
    for (let i = 0; i < sp.nWin; i++) {
      const to = i ? isoAdd(addMonISO(sp.to, -i), 0) : sp.to, from = i === sp.nWin - 1 ? sp.from : isoAdd(addMonISO(sp.to, -(i + 1)), 1);
      out.push({ from, to, best: bestRange(from, to, sp.R) });
    }
    return out;
  }
  function monthDays(ym) {
    const xs = realDays(ym || ymShift(0));
    return { n: xs.length, w: xs.filter(x => x.v > 0).length, l: xs.filter(x => x.v < 0).length };
  }
  const heroDayLbl = k => { const iso = isoDay(k); if (!iso) return String(k); const d = new Date(iso + 'T00:00:00'); return (d.getMonth() + 1) + '/' + d.getDate() + ' (' + DOWS[d.getDay()] + ')'; };
  function heroHTML() {
    const D = S.D;
    const h = heroNums();
    const mr = monthRealized();
    const ym0 = ymShift(0), mon = +ym0.slice(5);
    const sells = D.dayActs ? sum(Object.keys(D.dayActs).filter(k => k.slice(0, 7) === ym0), k => Math.max(0, num(D.dayActs[k].s) - num(D.dayActs[k].pay))) : D.events.filter(e => /매도/.test(e.k) && e.iso.slice(0, 7) === ym0).length;
    const tk = D.todayKey;
    const tr = KV(num(D.realized[tk]), D.hasKrw ? D.realizedK[tk] : null);
    const tcn = dayCnt(tk, true), tSells = tcn ? tcn.s : D.events.filter(e => /매도/.test(e.k) && e.iso.slice(0, 10) === isoDay(tk)).length;
    const trZero = Math.abs(num(D.realized[tk])) < 0.005;
    const md = monthDays(ym0), bsp = bestSpan(), best = bestRange(bsp.from, bsp.to, bsp.R);
    const fut = D.fut, futOk = !!fut.ts;
    const cmp = S.mobile;
    const vks = Object.keys(fut.snapshotTs || {}), ndex = vks.filter(isDex).length, exs = vks.length - ndex;
    const stale = arr(fut.staleExchanges);
    const rangeSeg = D.daily.length > 7 ? '<div class="seg rng pvx" role="group" aria-label="차트 기간">' + CH_RANGES.filter(r => r[0] <= 30 || S.hist.st !== 'none').map(r => '<button data-a="chartDays" data-v="' + r[0] + '" class="' + (S.chartDays === r[0] ? 'on' : '') + '" aria-pressed="' + (S.chartDays === r[0]) + '">' + r[1] + '</button>').join('') + '</div>' : '';
    const bestR = best ? topRcptSym(best.iso) : null;
    const bestChip = best ? '<button class="bestd" data-a="bestMonths" data-v="' + esc(best.iso) + '" aria-haspopup="dialog" title="' + esc(heroDayLbl(best.k) + ' 실현 ' + m(best.v, { sign: true }) + (best.sym ? ' · 기여 1위 ' + best.sym : '') + ' — 누르면 ' + (bsp.nWin > 1 ? '달마다 최고의 날' : '이 기간 최고의 날') + '을 고를 수 있어요' + (bestR ? '(' + bestR + ' 차익 영수증)' : '')) + '"><span class="k">최고의 날</span><span class="num">' + esc(heroDayLbl(best.k).replace(/ \(.\)$/, '')) + (best.sym ? '<span class="bsym"> · ' + esc(best.sym) + (best.more ? ' 등' : '') + '</span>' : '') + ' ' + m(best.v, { sign: true, compact: true }) + '</span>' + IC.right + '</button>' : '';
    const hw = S.chartDays > 30 && S.hist.st === 'loading' && !h.hist, hwL = (CH_RANGES.find(r => r[0] === S.chartDays) || [0, ''])[1];
    const chart = hw ? '<div aria-busy="true"><div class="chart chsk" aria-hidden="true"><i></i></div><div class="chart-x num">&nbsp;</div><div class="chart-foot"><span class="cap pvx" role="status" aria-live="polite">' + esc(hwL) + ' 곡선 받는 중…</span></div></div>'
      : h.pts && h.pts.length > 1 ? chartSVG(h.pts, h, best, bestChip) : '<div class="cap" style="margin-top:8px">일별 마감이 쌓이면 추이 차트가 표시돼요.</div>' + (bestChip ? '<div class="chart-foot">' + bestChip + '</div>' : '');
    const ap = h.ap ? '≈ ' : '';
    const at0 = h.today != null ? attOf(D.todayKey) : null;
    const todayChg = h.today == null ? '<span class="mut">전일 마감 없음</span>'
      : '<span class="' + (h.disc || h.split ? 'mut' : cls(h.today)) + '" title="' + esc((h.disc || h.split ? (h.flow != null ? flowTip(h.flow, D._todayFlowTop) : '하루 ±20% 초과 — 입출금 포함') : '') + (h.ap ? (h.disc || h.split ? ' · ' : '') + '전일 마감이 근사(≈)라 오늘 변화도 근사' : '')) + '"><b>' + ap + N('today', h.today, cmp ? 'sc' : 's') + '</b> <span class="pp">' + pctS(h.todayPct, 2) + '</span>' + (at0 ? '' : h.split ? ' <small>' + flowSplit(h.today, h.flow, D._todayFlowTop, true) + '</small>' : (h.disc ? ' <small>· 입출금 포함</small>' : '')) + '</span>';
    const lbl = '<span class="pvx">' + (S.chartDays === 7 ? '1주' : h.hist ? (CH_RANGES.find(r => r[0] === S.chartDays) || [0, ''])[1] : (h.pts ? h.pts.length : 30) + '일') + '</span>';
    const exH = h.hist && h.histFlowMiss ? '<span class="nw" title="최근 30일의 입출금(원화 입출금·외부 전송·잔고 정정)만 기간 변화에서 뺐어요 — 그보다 앞의 날은 입출금을 ' + (S.hist.flowBuilding ? '계산하는 중이라' : '따로 세지 않아') + ' 그대로 들어 있어요"> · 입출금은 최근 30일만 제외</span>' : '';
    const hp = S.hist.prog || {};
    const hcap = S.chartDays <= 30 || hw ? '' : S.hist.st === 'loading' && !h.hist ? '과거 곡선 불러오는 중…'
      : S.hist.st === 'err' ? '과거 곡선을 못 불러왔어요 — 다음 갱신 때 다시 받아요'
      : S.hist.building ? '과거 시세 모으는 중' + (num(hp.specs) ? ' (' + Math.min(100, Math.round(num(hp.done) / num(hp.specs) * 100)) + '%)' : '') + ' — 다 모으기 전 날은 점선(근사)'
      : (S.hist.st === 'ok' && !h.hist ? '30일보다 앞의 기록이 아직 없어요' : h.hist && h.histFlowMiss && S.hist.flowBuilding ? '과거 입출금 계산 중 — 끝나면 기간 변화에서 입출금을 모두 빼요' : '');
    const flTxt = h.rng != null && D.hasFlow ? '입출금 ' + m(h.flowSum, { sign: true }) + ' 제외 · 입출금 포함 변화 ' + m(h.rng, { sign: true }) : '';
    const exF = '<span class="nw" title="' + esc((flTxt ? flTxt + ' — ' : '') + '원화 입출금(은행 ↔ 거래소 — 쓰려고 뺀 돈·새로 넣은 돈)·외부 전송·거래소 잔고 정정은 매매 손익이 아니라서 기간 변화에서 뺐어요') + '"> · 입출금 제외</span>';
    const exX = h.hist && !h.histFlowMiss && h.nofxN ? '<span class="nw" title="' + esc(h.nofxN + '일은 그날 마감 환율 기록이 없어 원화 입출금 ' + krw(h.nofxK) + ' 를 기간 변화에서 빼지 못했어요(오늘 환율로 바꾸지 않음)') + '"> · 원화 입출금 ' + h.nofxN + '일 미반영</span>' : '';
    const rngTxt = h.rng != null && h.pts && h.pts.length > 2 ? '<b class="' + cls(h.adj) + '" title="' + esc(m(h.adj, { sign: true }) + (flTxt && Math.abs(h.rng - h.adj) >= 0.5 ? ' · ' + flTxt : '')) + '">' + m(h.adj, { sign: true, compact: true }) + '</b> <span class="pp ' + cls(h.adj) + '">' + pctS(h.first.val ? retPct(h.first.val, h.first.val + h.rng, h.flowSum) : null, 2) + '</span> <span class="mut">' + lbl + (h.hist && h.histFlowMiss ? exH : (D.hasFlow ? (Math.abs(h.rng - h.adj) >= 0.5 ? exF : '') : (h.steps.length ? exF : ''))) + exX + '</span>' : '';
    const dex = D.debts.map(x => x.ex).filter((v, i, a0) => a0.indexOf(v) === i), dsym = D.debts.map(x => x.sym).filter((v, i, a0) => a0.indexOf(v) === i);
    const debt = D.debts.length ? '<span class="hs num debtln" title="' + esc(D.debtTip()) + '">' + esc(D.debtLbl) + ' <b class="dn">' + m(D.debtUsd, { sign: true, compact: cmp }) + '</b> <span class="mut">' + nbDot(esc(dex.join(' · ') + ' ' + dsym.join(' · '))) + ' · 상환 전 · 총자산에 이미 차감</span></span>' : '';
    const tsub = rbLine();
    const totalCard = '<section class="card total" aria-label="자산 요약"><div class="thd"><div class="tleft">'
      + '<div class="trow"><span class="tlab">총자산 <i id="heroWhen"></i></span>' + wowSlot('dash.total') + '</div><span class="tv num" id="heroBig"' + (cmp ? ' title="' + esc(m(D.total)) + '"' : '') + '>' + N('total', D.total, cmp ? 'mc' : 'm') + '</span>'
      + '<span class="tchg num" id="heroChg">' + (hw ? '<span class="skl chskl" aria-hidden="true"></span>' : rngTxt || '&nbsp;') + '</span>' + (tsub ? '<span class="tsub">' + tsub + '</span>' : '') + '</div>' + rangeSeg + '</div>' + oaDashLine() + chart + (hcap ? '<div class="cap histcap" role="status">' + hcap + '</div>' : '') + (D.prov && D.prov.note ? '<div class="cap histcap" role="status">' + esc(D.prov.note) + '</div>' : '') + '</section>';
    const futNet = num((fut.pnlBreak || {}).net != null ? fut.pnlBreak.net : fut.realizedTotal);
    const futOpen = futOk && num(fut.posCount) > 0;
    const futV = !futOk ? '<span class="mut">수집 대기</span>' : futOpen ? '<span class="' + cls(num(fut.upnl)) + '"' + (fut.upnlPartial ? ' title="코인 정산 포지션 일부는 시세가 없어 빼고 더했어요"' : '') + '>' + upnlH(fut.upnl, null, { sign: true, compact: true }) + '</span>' : '<span class="' + cls(futNet) + '">' + m(futNet, { sign: true, compact: true }) + '</span>';
    const futS = '<span class="pvx">' + (futOpen ? '오픈 ' + num(fut.posCount) + '건 · 규모 </span>' + (fut.notional == null ? '—' : mN(num(fut.notional), { compact: true })) + '<span class="pvx">' : '오픈 포지션 없음') + (exs || ndex ? ' · ' + (exs ? '거래소 ' + exs + '곳' : '') + (ndex ? (exs ? ' · ' : '') + '덱스 ' + ndex + '곳' : '') : Object.keys(fut.realizedByDate || {}).length ? '' : ' · ' + (exLinked() ? '첫 수집 전' : '거래소 연결 전')) + '</span>' + (futOpen ? ' · 누적 <span class="' + cls(futNet) + '">' + mN(futNet, { sign: true, compact: true }) + '</span>' : '') + (stale.length ? ' · ' + esc(stale.map(x => EX_NAMES[x] || x).join(', ')) + ' 제외' : '');
    const futTip = futFxNote(futNet);
    const tEvs = dayFull(tk) || (partHave('ev') ? (D.evByDay.get(tk) || []) : null), tBuys = [];
    if (tEvs) tEvs.filter(e => /매수/.test(e.k)).forEach(e => { if (tBuys.indexOf(e.sym) < 0) tBuys.push(e.sym); });
    const tRec = tcn ? tcn.n : tEvs ? tEvs.length : null;
    const tTip = '오늘 실현 · 매도 ' + tSells + '건' + (tcn && tcn.pay ? ' · 스왑 지불 ' + tcn.pay + '건' : '') + (tRec != null ? ' · 기록 ' + tRec + '건' : '') + (tBuys.length ? ' · 새로 산 코인 ' + tBuys.slice(0, 6).join(' · ') + (tBuys.length > 6 ? ' 외 ' + (tBuys.length - 6) + '종' : '') : '') + ' — 누르면 오늘 기록';
    const kq = '<div class="kpis4">'
      + '<button class="card kq htoday" data-a="goDay" data-v="' + esc(tk) + '" title="' + esc(tTip) + '"><span class="ql">오늘 실현 <i>· ' + esc(heroDayLbl(tk)) + '</i></span><span class="qv num' + (trZero ? ' z' : ' ' + cls(tr)) + '">' + N('treal', tr, trZero ? 'm' : 'sc') + '</span><span class="qs pvx"><span class="nowrap">매도 ' + tSells + '건 ·</span> ' + (tRec != null ? '<span class="nowrap">기록 ' + tRec + '건 ·</span> ' : '') + '<span class="nowrap">23:59 마감</span></span></button>'
      + '<button class="card kq hmonth" data-a="goJournalPeriod" data-v="thismonth" title="매도 체결 기준 · 현물+선물 — 누르면 매매일지 이번 달"><span class="ql">' + mon + '월 실현</span><span class="qv num ' + cls(mr) + '">' + N('month', mr, 'sc') + '</span>'
      + '<span class="qs pvx">' + (md.n ? '<span title="날 단위 — 그날 실현(현물+선물)이 + 인 날 / − 인 날(달력 칩과 같은 셈). 매매일지의 승률(청산 사이클 단위)과 달라요"><span class="nowrap">수익 ' + md.w + '일 ·</span> <span class="nowrap">손실 ' + md.l + '일 ·</span></span> ' : '') + '<span class="nowrap" title="그날 기록 목록의 매도 기록 수(스왑 지불 레그 제외) · 체결 수는 매매일지">매도 ' + sells + '건</span></span></button>'
      + '<button class="card kq kpi" data-a="goJournalHeld" title="원가가 확인된 수량만 평가했어요 — 누르면 매매일지 보유 중"><span class="ql">평가손익</span><span class="qv num ' + cls(D.unreal) + '">' + N('unreal', D.unreal, 'sc') + '</span><span class="qs num"><span class="nowrap">원가 확인분 ·</span> <span class="nowrap"><span class="' + cls(D.unreal) + '">' + pctS(D.roiAll, 1) + '</span> ·</span> <span class="nowrap">원가 ' + mN(D.totalCost, { compact: true }) + '</span></span></button>'
      + '<button class="card kq kpi fut" data-a="openFut"' + (futTip ? ' title="' + esc(futTip) + '"' : '') + '><span class="ql">' + (futOpen ? '선물 포지션' : '선물 누적') + (stale.length ? ' <span class="pill w sm">수집 지연</span>' : '') + '</span><span class="qv num">' + futV + '</span><span class="qs num">' + futS + '</span></button></div>';
    const why = '<section class="card why" aria-label="오늘 무엇이 움직였나"><div class="wh"><h2>오늘 무엇이 움직였나</h2><span class="num whv" id="heroToday">' + todayChg + '</span></div>'
      + (at0 ? attBars(at0, D.todayKey, true) : '<div class="cap">' + (h.today == null ? '전일 마감이 쌓이면 오늘 변동을 시세·입출금·환율로 나눠 보여요' : '오늘은 분해 기록이 아직 없어요 — 다음 수집 때 시세·입출금·환율로 나눠 보여요') + '</div>') + '</section>';
    return '<div class="hero">' + totalCard + kq + levHTML() + lpCardHTML() + '<div class="dmid">' + why + todoHTML() + '</div></div>';
  }
  function attQ(n) {
    if (n == null || !isFinite(n)) return '—';
    if (S.hide) return (n < 0 ? '−' : '') + pvW(PVM.q);
    n = KS(n);
    const a = Math.abs(n);
    let t;
    if (a >= 9999.5e4) t = trimZeros((a / 1e8).toFixed(2)) + '억';
    else if (a >= 1e5) { const v = a / 1e4; t = (v >= 999.95 ? nf('ko-KR').format(Math.round(v)) : trimZeros(v.toFixed(1))) + '만'; }
    else if (a >= 1000) t = nf('ko-KR').format(Math.round(a));
    else if (a >= 1) t = trimZeros(a.toFixed(a >= 100 ? 1 : a >= 10 ? 2 : 3));
    else if (a === 0) t = '0';
    else t = trimZeros(a.toFixed(Math.min(12, 2 - Math.floor(Math.log10(a)))));
    return (n < 0 && /[1-9]/.test(t) ? '−' : '') + rw(t);
  }
  const attPct = p => (p == null || !isFinite(p) ? '—' : Math.abs(p) >= 999.95 ? (p > 0 ? '+' : '−') + nf('en-US', 0, 0).format(Math.abs(p)) + '%' : pctS(p, 1));
  const ATT_PXK = { live: '실시간 화면 시세', c: '그 시각 1분봉', d: '그날 일봉 마감', seed: '옛 마감 기록', now: '근사 — 처음 계산한 시각 시세', mix: '그룹마다 다름' };
  const ATT_SRCN = { coingecko: '코인게코', geckoterminal: 'GeckoTerminal(DEX)' };
  function attSrcNm(s) {
    return String(s || '').split(' · ').filter(Boolean).map(x => {
      const i = x.indexOf(':'), v = i > 0 ? x.slice(0, i) : x, mk = i > 0 ? x.slice(i + 1) : '';
      return (EX_NAMES[v] || ATT_SRCN[v] || v) + (mk ? ' ' + mk : '');
    }).join(' · ');
  }
  const attPxSrc = (k, s) => (s ? attSrcNm(s) + '(' + (ATT_PXK[k] || '종류 모름') + ')' : (ATT_PXK[k] || '가격 종류 모름'));
  const attSpG = x => (x.gs && x.gs.find(g => g.spike)) || x;
  function attSpNote(x) {
    const g = attSpG(x), r = num(g.rx) > 0 ? num(g.rx) : g.p1 / g.p0;
    const times = r >= 1 ? nf('en-US', 0, r >= 10 ? 0 : 1).format(r) + '배' : '1/' + nf('en-US', 0, 1 / r >= 10 ? 0 : 1).format(1 / r) + '로';
    const what = g.fr === 'next' ? '그날 마감가가 다음 날 마감가와 ' + times + ' 차이' : g.fr === 'prev' ? '전일 마감가가 그 전날과 ' + times + ' 차이' : '하루에 ' + times;
    const s1 = attPxSrc(g.k, g.src), s0 = attPxSrc(g.k0, g.k0 === 'd' ? (g.src0 || g.src) : '');
    return what + ' — ' + (s1 === s0 ? '출처 ' + s1 : '그날 ' + s1 + ' · 전일 ' + s0) + ' · 시세 출처를 확인해 주세요';
  }
  const attSpTip = x => { const g = attSpG(x); return (g.fr === 'day' || !g.fr ? '가격이 하루에 3배 넘게 움직였어요' : '가격이 이웃 날과 3배 넘게 달라요') + ' — 시세 출처 확인: ' + attPxSrc(g.k, g.src); };
  function attTbl(a, k) {
    if (!a || !a.top.some(t => t.x)) return '';
    const D = S.D, isT = k === D.todayKey, krwM = S.cur !== 'USD';
    const V = v => '<b class="' + clsV(v) + '">' + m(v, { sign: true, compact: true }) + '</b>';
    const pxS = (p, kk) => '<span class="nw">' + (kk === 'now' ? '≈' : '') + px(p) + '</span>';
    const fx = krwM ? ' × 그날 환율' : '';
    const row = t => {
      const x = t.x;
      if (!x) return '<tr><td><span class="axc">' + icon(t.sym, 'xs', D.symLogo[t.sym.toUpperCase()] || {}) + '<span class="nm">' + esc(t.sym) + '</span></span></td><td class="q">—</td><td class="p">—</td><td class="' + cls(t.pct) + '">' + attPct(t.pct) + '</td><td>' + V(t.v) + '</td></tr>';
      const tip = '전일 마감가 ' + px(x.p0) + ' — ' + attPxSrc(x.k0, x.k0 === 'd' ? (x.src0 || x.src) : '') + ' → ' + (isT ? '지금 ' : '그날 마감가 ') + px(x.p1) + ' — ' + attPxSrc(x.k, x.src);
      const fml = '전일 수량 ' + attQ(x.q) + ' × (' + px(x.p1) + ' − ' + px(x.p0) + ')' + fx + ' = ' + m(t.v, { sign: true });
      const gs = x.gs.length > 1 && Math.max.apply(null, x.gs.map(g => g.p0)) > Math.min.apply(null, x.gs.map(g => g.p0)) * 1.05 ? x.gs.slice(0, 3) : [];
      return '<tr class="' + (x.spike ? 'sp' : '') + '"><td><span class="axc">' + icon(t.sym, 'xs', D.symLogo[t.sym.toUpperCase()] || {}) + '<span class="nm">' + esc(t.sym) + '</span>'
        + (x.gn > 1 ? '<span class="axgn" title="' + esc('같은 이름 그룹 ' + x.gn + '개 — 가격은 수량 가중(전일 수량 × 가격 차 = 그룹 합)') + '">×' + x.gn + '</span>' : '')
        + (x.spike ? '<span class="axbd" title="' + esc(attSpTip(x)) + '">튐 주의</span>' : '') + '</span></td>'
        + '<td class="q">' + attQ(x.q) + '</td><td class="p" title="' + esc(tip) + '">' + pxS(x.p0, x.k0) + ' → ' + pxS(x.p1, x.k) + '</td>'
        + '<td class="' + cls(t.pct) + '">' + attPct(t.pct) + '</td><td title="' + esc(fml) + '">' + V(t.v) + '</td></tr>'
        + (x.spike ? '<tr class="axn"><td colspan="5">' + esc(attSpNote(x)) + '</td></tr>' : '')
        + gs.map(g => '<tr class="sub"><td>그룹' + (g.spike ? ' <span class="axbd" title="' + esc(attSpTip(g)) + '">튐</span>' : '') + '</td><td class="q">' + attQ(g.q) + '</td><td class="p">' + pxS(g.p0, g.k0) + ' → ' + pxS(g.p1, g.k) + '</td><td class="' + cls(g.p1 - g.p0) + '">' + attPct((g.p1 / g.p0 - 1) * 100) + '</td><td>' + V(g.v) + '</td></tr>').join('');
    };
    const coinV = sum(a.top, t => t.v) + a.etc.v;
    let foot = '';
    if (attSig(a, a.mk - coinV)) {
      const ps = (a.v2 ? [['그날 사고판 분', a.ur], ['원장 밖 코인', a.xm], ['같은 코인 가격 묶음 차', a.gx]] : [['원화 예수금 달러 환산', a.kx]]).filter(p => attSig(a, num(p[1])));
      const left = a.mk - coinV - sum(ps, p => num(p[1]));
      if (Math.abs(left) * (krwM ? rate() : 1) >= (krwM ? 0.5 : 0.005)) ps.push(['기타', left]);
      foot = '<div class="axf">시세 변동 ' + V(a.mk) + ' = 표의 코인 ' + V(coinV) + ps.map(p => ' · ' + p[0] + ' ' + V(num(p[1]))).join('') + '</div>';
    }
    return '<div class="axt"><div class="axh"><b>시세 변동 코인별 — 전일 수량 × 가격 변화</b><span class="pvx">' + (isT ? '가격 = 전일 마감가 → 지금 시세' : '가격 = 그날 마감가(KST 24시)') + (krwM ? ' · 달러 — 기여는 그날 환율로 원화' : '') + '</span></div>'
      + '<div class="axs"><table class="axtb num"><thead><tr><th scope="col">코인</th><th scope="col">전일 수량</th><th scope="col">' + (isT ? '전일 마감 → 지금' : '전일 마감 → 그날 마감') + '</th><th scope="col">변동</th><th scope="col">기여</th></tr></thead><tbody>'
      + a.top.map(row).join('')
      + (a.etc.n ? '<tr class="etc"><td>그 밖 ' + a.etc.n + '개</td><td></td><td></td><td></td><td>' + V(a.etc.v) + '</td></tr>' : '')
      + '</tbody></table></div>' + foot + '</div>';
  }
  function attBars(a, k, dash) {
    const rows = [['시세', a.mk, 'mk']].concat(attItemsK(a).map(x => [x.l, x.v, x.key]));
    const mx = Math.max.apply(null, rows.map(x => Math.abs(num(x[1]))).concat([1e-9]));
    const open = S.attOpen === k;
    const mob = S.mobile;
    const dA = x => ' data-a="attdOpen" data-v="' + esc('d|' + k + '|' + x[2]) + '" aria-haspopup="dialog" aria-label="' + esc(x[0] + ' ' + m(num(x[1]), { sign: true, compact: true }) + ' — 누르면 무엇 때문인지') + '"';
    const aCv = IC.right.replace('<svg', '<svg class="acv" aria-hidden="true"');
    const tog = '<button class="link atttog" data-a="attTog" data-v="' + esc(k) + '" aria-expanded="' + open + '">' + (open ? '접기' : '자세히') + IC.chev.replace('<svg', '<svg class="cv' + (open ? ' o' : '') + '" width="13" height="13"') + '</button>';
    const bars = mob && dash
      ? '<div class="attx achips">' + rows.slice().sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).map(x => '<button type="button" class="achip abtn"' + dA(x) + '><span>' + x[0] + '</span> <b class="num ' + cls(x[1]) + '">' + m(x[1], { sign: true, compact: true }) + '</b>' + aCv + '</button>').join('') + '</div>'
      : '<div class="attx abars abtns" role="group" aria-label="자산 변동 분해 — 줄을 누르면 무엇 때문인지">' + rows.map(x => { const v = num(x[1]), w = Math.abs(v) / mx * 50;
        return '<button type="button" class="abr abtn"' + dA(x) + '><span class="al">' + x[0] + '</span><span class="atrk" aria-hidden="true"><i class="' + (v >= 0 ? 'p' : 'n') + '" style="left:' + (v >= 0 ? 50 : 50 - w).toFixed(2) + '%;width:' + Math.max(w, Math.abs(v) >= 0.005 ? 0.6 : 0).toFixed(2) + '%"></i><b></b></span><span class="av num ' + cls(v) + '">' + m(v, { sign: true, compact: true }) + aCv + '</span></button>'; }).join('') + '</div>';
    const tbl0 = dash ? '' : attTbl(a, k), tN = a.top.length + (a.etc.n ? 1 : 0);
    const tbl = tbl0 ? uiFold('atttbl', { cls: 'attf', head: '<b>시세 코인별 ' + a.top.length + '개' + (a.etc.n ? ' + 그 밖 ' + a.etc.n + '개' : '') + '</b><span class="cap">' + esc(a.top.slice(0, 5).map(t => t.sym).join(' · ')) + ' — 전일 수량 × 가격 변화</span>', body: () => tbl0, label: '시세 변동 코인별 표 ' + tN + '줄' }) : '';
    const shown = a.top.slice(0, mob || !dash ? 3 : 5).filter(t => Math.abs(t.v) >= 0.005);
    const mv = tbl ? tbl + '<div class="axtg">' + tog + '</div>' : shown.length ? '<div class="amv"><span class="cap">많이 움직인 코인</span>' + shown.map(t => '<span class="mchip" title="' + esc(t.sym + ' 시세 기여 ' + m(t.v, { sign: true })) + '">' + icon(t.sym, 'xs', S.D.symLogo[t.sym.toUpperCase()] || {}) + esc(t.sym) + ' <span class="num ' + cls(t.pct != null ? t.pct : t.v) + '">' + (t.pct != null ? pctS(t.pct, 1) : m(t.v, { sign: true, compact: true })) + '</span></span>').join('') + '<span class="sp"></span>' + tog + '</div>' : '<div class="amv"><span class="sp"></span>' + tog + '</div>';
    return '<div class="attl ' + (dash ? 'hatt ' : '') + 'abox"' + ' title="' + esc(attLine(a, 5, false)) + '">' + (a.ap ? '<div class="cap">≈ 근사 — 시세 기록 없는 자산은 추정가라 시세 기여가 0</div>' : '') + bars + mv + '</div>' + (open ? attDetail(a, k, !!tbl) : '');
  }
  const ATTD_LBL = { mk: '시세', rz: '현물 실현', rzf: '선물 실현', fl: '입출금', fx: '환율', fo: '선물 미반영', un: '원가 미확인', op: '기초 잔고 정정', tr: '매매', oth: '나머지', ur: '사고판 분(→실현)' };
  const ATTD_PG = 20;
  const L0 = v => esc(v);
  const ATTD_ICO = { fl: 'send', krw: 'bank', usd: 'coin', cvt: 'scale', fut: 'scale', lp: 'layers', gas: 'fuel', rest: 'info', unp: 'alert', mv: 'undo', grp: 'layers', rb: 'wallet', stk: 'coin', day: 'cal', fold: 'layers' };
  const ATTD_NOUN = { mk: '코인·몫', rz: '코인·LP', rzf: '종목', fl: '이동', fx: '몫', fo: '거래소', un: '코인', op: '코인', tr: '몫', oth: '몫', ur: '몫' };
  const ATTD_NEED = { mk: 1, rzf: 1, fl: 1, fx: 1, fo: 1, un: 1, op: 1, oth: 1, ur: 1 };
  function attdWhat(key, isT) {
    return ({ mk: isT ? '전일 보유 코인 × 가격 변화(전일 마감 → 지금) + 원장 밖 코인 + 그날 사고판 분' : '전일 보유 코인 × 가격 변화(그날 마감가) + 원장 밖 코인 + 그날 사고판 분',
      rz: '그날 판 것의 원가 대비 손익(LP 수수료·스테이킹 보상 포함) — 위 칸 총 실현의 현물 몫', rzf: '그날 선물 정산(정산 + 수수료 + 펀딩) — 위 칸 총 실현의 선물 몫',
      fl: '밖에서 들어오고 나간 돈 — 내 지갑·거래소끼리 이동은 서로 지움', fx: S.cur === 'USD' ? '원화 예수금의 달러 환산 몫(그날 USDT 종가 차)' : '달러 자산·원화 예수금의 환율 몫 + 실현을 체결 시각 환율로 센 차',
      fo: '그날 총자산 변화에 아직 안 든 선물 정산 — 줄 합을 전일 대비와 맞추려고 빼요', un: '원가를 모르는 코인을 판 금액 − 그날 가격 평가(실현·평가로 못 나눔)',
      op: '전부터 있던 보유를 이날 원장에 넣음(발견·재점검 기초 잔고 × 그날 가격) — 실제로 들어온 돈 아님', tr: '마감가 대비 체결 차(수수료·가스 포함)',
      oth: '다른 줄로 설명되지 않는 몫 — 이름 붙은 몫 · 작아서 합친 줄 · 근사·반올림', ur: '그날 사고판 코인별 — 실현으로 옮겨간 평가 손익 + 그날 산 코인 평가 변화' })[key] || '';
  }
  function attdPurge() { S.attdC = null; S.attdGen = (S.attdGen || 0) + 1; }
  function attdCache() { const D = S.D, c = S.attdC; return c && c.at === D.builtAt ? c : (S.attdC = { at: D.builtAt, days: {}, st: {} }); }
  function attdNeed(lo, hi) {
    if (!S.D || !isISO(lo) || !isISO(hi)) return 'err';
    if (S.hide || S.rand) { S.attdC = null; return 'private'; }
    const C = attdCache(), key = lo + '|' + hi, gen = S.attdGen || 0;
    if (C.st[key]) return C.st[key];
    C.st[key] = 'load';
    fetch('/api/att_detail?from=' + lo + '&to=' + hi + (lo !== hi ? '&lite=1' : ''), { cache: 'no-store' })
      .then(r => { if (r.status === 401) { onUnauthorized(); throw new Error('401'); } if (r.status === 404) return { ok: true, days: {}, old: 1 };
        return r.json().catch(() => null).then(d => { if (!r.ok || !d || !d.ok) throw new Error((d && d.error) || ('HTTP ' + r.status)); return d; }); })
      .then(d => { if (S.hide || S.rand || S.attdC !== C || (S.attdGen || 0) !== gen) { delete C.st[key]; return; }
        if (d.builtAt != null && C.at != null && +d.builtAt !== +C.at) { C.st[key] = 'stale'; return; }
        const dd = d.days && typeof d.days === 'object' ? d.days : {}, lite = lo !== hi;
        Object.keys(dd).forEach(k => { if (isISO(k) && dd[k] && typeof dd[k] === 'object' && !(lite && C.days[k] && !C.days[k]._lite)) C.days[k] = lite ? Object.assign({ _lite: 1 }, dd[k]) : dd[k]; });
        C.st[key] = d.old ? 'old' : 'ok'; })
      .catch(() => { if (S.attdC === C && (S.attdGen || 0) === gen) C.st[key] = 'err'; })
      .then(() => { if (S.sheet && S.sheet.k === 'attd' && S.attdC === C) renderOverlay(); });
    return 'load';
  }
  const attdIt = (id, l, v, o) => Object.assign({ id: String(id), l: String(l), v: num(v), s: '' }, o || {});
  function attdFit(items, want, restL, restS) {
    const out = items.filter(x => x && isFinite(x.v) && x.v !== 0);
    const d = num(want) - sum(out, x => x.v), tiny = Math.abs(d) <= 0.006 * (out.length + 1);
    if (d !== 0 && isFinite(d)) out.push(attdIt('_rest', tiny ? '반올림 끝전' : restL, d, { s: tiny ? esc('항목마다 센트로 반올림한 차') : (restS || ''), rest: tiny ? 2 : 1, ico: 'rest' }));
    return out;
  }
  function attdUr(dt, a, kf, more) {
    const du = dt && dt.ur && typeof dt.ur === 'object' ? dt.ur : null, out = [];
    if (du) arr(du.rows).forEach(c => { if (Array.isArray(c) && c[0] != null) out.push(attdIt('u:' + c[0], String(c[0]), num(c[6]) * kf,
      { sym: String(c[0]), s: attdUrSub(c, kf), a: 'attdUx', av: 'u:' + c[0] })); });
    if (du) more(out, 'ur', '종');
    if (du && num(du.fee)) out.push(attdIt('u:_fee', '수수료·가스 레그', num(du.fee) * kf, { ico: 'gas', s: esc('그날 쓴 수수료·가스(그날 가격)') }));
    if (du && num(du.lp)) out.push(attdIt('u:_lp', 'LP 예치·회수 레그', num(du.lp) * kf, { ico: 'lp', s: esc('LP 에 넣고 뺀 원금(그날 가격)') }));
    return attdFit(out, a.ur, du ? '그 밖(스테이블·원화 체결·LP 실현)' : '코인별로 나누지 못한 몫',
      esc(du ? '스테이블 환전 차익·원화 체결 환율 차·LP 회수 실현·스테이킹 보상' : '서버를 업데이트하면 코인별로 보여요'));
  }
  function attdUrSub(c, kf) {
    const M = v => m(num(v) * kf, { compact: true }), Mx = v => m(num(v) * kf, { sign: true, compact: true }), b = [];
    const nz = v => Math.abs(num(v)) >= 0.005, [sl, by, rz, mo, mn, , cn, uk] = [1, 2, 3, 4, 5, 6, 7, 8].map(i => num(c[i]));
    const co = sl - uk - rz, bt = [nz(by) ? '산 돈 ' + M(by) : '', nz(cn) ? '그중 판 것 원가 ' + M(cn) : ''];
    if (nz(sl)) b.push('판 돈 ' + M(sl) + (nz(uk) ? ' − 원가 모름 ' + M(uk) : '') + ' − 원가 ' + M(co) + ' = 실현 ' + Mx(rz));
    else if (nz(rz)) b.push('실현 ' + Mx(rz));
    if (nz(by) || nz(mn)) b.push('그날 산 몫: ' + bt.concat(['마감까지 평가 변화 ' + Mx(mn)]).filter(Boolean).join(' · '));
    const ot = [nz(co - cn) ? '판 것 원가 ' + M(co - cn) : '', nz(mo) ? '평가 이동 ' + Mx(mo) : ''].filter(Boolean);
    if (ot.length) b.push('이미 평가에 있던 몫(실현으로 이동): ' + ot.join(' · '));
    return b.concat(['이 코인이 사고판 분에 주는 값 ' + Mx(c[6])]).join('<br>');
  }
  function attdParts(k, det) {
    const D = S.D, x = D && D.dayMap.get(k), a = x ? attOf(k) : null;
    if (!a) return null;
    const raw = x.att || {}, iso = isoDay(k), isT = k === D.todayKey, krw = S.cur !== 'USD';
    const kf = krw && !isT && x.valKrw != null && num(x.usdt) > 0 ? num(x.usdt) / rate() : 1;
    const dt = det && typeof det === 'object' ? det : null, P = {};
    const L = v => esc(v);
    const mk = [];
    if (dt && Array.isArray(dt.mk)) dt.mk.forEach(c => { if (!Array.isArray(c) || c[0] == null) return; const sy = String(c[0]);
      mk.push(attdIt('c:' + sy, sy, num(c[1]) * kf, { sym: sy, pct: c[2] == null ? null : num(c[2]), q: c.length > 5 ? num(c[3]) : null, p0: num(c[4]), p1: num(c[5]), a: 'attdCoin', av: sy })); });
    else {
      a.top.forEach(t => mk.push(attdIt('c:' + t.sym, t.sym, t.v, { sym: t.sym, pct: t.pct, q: t.x ? t.x.q : null, p0: t.x ? t.x.p0 : 0, p1: t.x ? t.x.p1 : 0, a: 'attdCoin', av: t.sym })));
      if (a.etc.n) mk.push(attdIt('etc', '그 밖 ' + a.etc.n + '종', a.etc.v, { ico: 'grp', s: L('작은 코인들의 시세 기여 합') }));
    }
    if (a.v2) {
      if (dt && Array.isArray(dt.xm) && dt.xm.length) dt.xm.forEach(c => { if (Array.isArray(c)) mk.push(attdIt('x:' + c[0], String(c[0]) + ' · 원장 밖', num(c[1]) * kf, { sym: String(c[0]), s: L('업비트 미매칭 코인 — 전일 수량 × 개당 가격 변화') })); });
      else if (a.xm) mk.push(attdIt('xm', '원장 밖 코인(업비트 미매칭)', a.xm, { ico: 'grp' }));
      if (a.ur) mk.push(attdIt('ur', '그날 사고판 분' + (attMvd(a) ? '(→실현)' : ''), a.ur, { ico: 'mv', s: L('판 코인의 평가 손익이 실현 줄로 옮겨간 몫 + 그날 산 코인의 마감까지 평가 변화') + ' · 누르면 코인별', a: 'attdGo', av: 'd|' + k + '|ur' }));
      if (a.gx) mk.push(attdIt('gx', '같은 코인 가격 묶음 차', a.gx, { ico: 'grp', s: L('같은 코인을 체인·거래소마다 조금 다른 값에 매긴 차') }));
      if (num(raw.fpx)) mk.push(attdIt('fpx', '입출금 기준가 교정', num(raw.fpx) * kf, { ico: 'fl', s: L('입출금 줄은 교정 전 가격 · 평가는 지금 고정가로 센 차') }));
    } else if (!krw && num(raw.kx)) mk.push(attdIt('kx', '원화 예수금 달러 환산', num(raw.kx) * kf, { ico: 'krw' }));
    const mo = dt && dt.more && typeof dt.more === 'object' ? dt.more : {};
    const more = (lst, key, noun) => { const x = mo[key]; if (Array.isArray(x) && num(x[1])) lst.push(attdIt(key + ':_more', '그 밖 ' + num(x[0]) + noun, num(x[1]) * kf, { ico: 'grp', more: 1, s: L('목록에 안 실은 작은 항목들의 합') })); };
    more(mk, 'mk', '종'); more(mk, 'xm', '종(원장 밖)');
    const mkMore = !mo.mk && dt && num(dt.mkN) > arr(dt.mk).length ? num(dt.mkN) - arr(dt.mk).length : 0;
    P.mk = attdFit(mk, a.mk, mkMore ? '그 밖 ' + mkMore + '종' : '그 밖(반올림·기준가)', L(mkMore ? '목록에 안 실은 작은 코인들의 기여 합' : '코인별 반올림·기준가 차'));
    P.ur = attdUr(dt, a, kf, more);
    const rz = [], rzf = [], fo = [];
    if (a.v2) {
      dayContrib(iso).filter(r => !r.fut).forEach(r => { const v = KV(r.v, r.vk), sy = String(r.sym);
        if (r.lp) { const lk = r.lpN ? '' : String((r.p && r.p.key) || ''), pool = String(r.lpN ? r.pool : (r.p && r.p.sym) || r.sym);
          rz.push(attdIt('lp:' + pool + '|' + lk, sy, v, { ico: 'lp', s: L('LP 수수료·회수 손익' + (r.lpN ? ' · ' + r.lpN + '개' : '')) + ' · 누르면 LP', a: 'attdLp', av: iso + '|' + pool + '|' + lk })); }
        else if (r.gas) rz.push(attdIt('gas:' + sy, '가스(매매 외)', v, { ico: 'gas', s: L('실패·승인·전송·브릿지·LP 가스 — 실현에서 뺌') }));
        else if (r.stk) rz.push(attdIt('stk:' + sy, sy, v, { ico: 'stk', s: L('스테이킹 보상 — 받은 시각 시가') }));
        else rz.push(attdIt('c:' + sy, sy, v, { sym: sy, s: L('판 것의 원가 대비 손익') + ' · 누르면 차익 영수증', a: 'attdRc', av: iso + '|' + sy })); });
      P.rz = attdFit(rz, a.rz, '코인별로 나누지 못한 실현', L('코인·LP별 줄에 안 든 $0.005 미만 조각·반올림'));
      const kvF = (u, kr) => KV(u, D.hasKrw ? (kr != null && isFinite(kr) ? num(kr) : u * rate()) : null);
      const exD = arr(((D.fut || {}).realizedByDateEx || {})[iso]).filter(e => e && isFinite(+e.usd));
      if (dt && Array.isArray(dt.fut) && dt.fut.length) dt.fut.forEach(f => { if (!Array.isArray(f)) return; const ex = String(f[0] || ''), nm = String(f[1] || EX_NAMES[ex] || ex || '선물'), sy = String(f[2] || '—');
        rzf.push(attdIt('f:' + ex + ':' + sy, sy === '—' ? nm + ' 선물' : futSym(sy), kvF(num(f[3]), f[4] == null ? null : num(f[4])), { ico: 'fut',
          s: L(nm) + (num(f[5]) ? ' · <span class="pvx">정산 ' + num(f[5]) + '건</span>' : '') + (num(f[6]) ? ' · 수수료·펀딩 포함' : '') + ' · 누르면 선물 영수증', a: 'attdFr', av: iso + '|' + ex })); });
      else exD.forEach(e => rzf.push(attdIt('f:' + e.exKey + ':', String(e.ex || EX_NAMES[e.exKey] || '선물'), kvF(num(e.usd), e.krw == null ? null : num(e.krw)), { ico: 'fut',
        s: (num(e.n) ? '<span class="pvx">정산 ' + num(e.n) + '건</span> · ' : '') + '누르면 선물 영수증', a: 'attdFr', av: iso + '|' + String(e.exKey || '') })));
      if (dt && Array.isArray(dt.fut) && dt.fut.length && Array.isArray(mo.fut) && (num(mo.fut[1]) || (mo.fut.length > 2 && num(mo.fut[2])))) {
        const fx9 = mo.fut;
        rzf.push(attdIt('fut:_more', '그 밖 ' + num(fx9[0]) + '종목', kvF(num(fx9[1]), fx9.length > 2 && fx9[2] != null ? num(fx9[2]) : null), { ico: 'grp', more: 1, s: L('목록에 안 실은 작은 항목들의 합') }));
      }
      P.rzf = attdFit(rzf, a.rzf, '그 밖 정산', L('거래소·종목별 줄에 안 든 정산 몫(정산 시각 환율 차 포함)'));
      if (a.fo) {
        const fbm = {};
        if (dt && Array.isArray(dt.fb)) dt.fb.forEach(f => { if (Array.isArray(f)) fbm[String(f[0])] = num(fbm[String(f[0])]) + num(f[1]); });
        if (num(raw.fb)) {
          const ks = []; Object.keys(fbm).concat(exD.map(e => String(e.exKey || ''))).forEach(e => { if (ks.indexOf(e) < 0) ks.push(e); });
          ks.forEach(ek => { const e = exD.find(z => String(z.exKey || '') === ek), ru = e ? num(e.usd) : 0, fv = num(fbm[ek]), v = (fv - ru) * kf;
            if (v) fo.push(attdIt('fo:' + ek, String((e && e.ex) || EX_NAMES[ek] || ek || '선물'), v, { ico: 'fut', s: '그날 정산 ' + m(ru * kf, { sign: true, compact: true }) + ' 중 총자산 반영 ' + m(fv * kf, { sign: true, compact: true }) })); });
        } else exD.forEach(e => fo.push(attdIt('fo:' + e.exKey, String(e.ex || EX_NAMES[e.exKey] || '선물'), -kvF(num(e.usd), e.krw == null ? null : num(e.krw)), { ico: 'fut', s: L('대사가 아직 총자산에 안 넣은 정산') })));
        P.fo = attdFit(fo, a.fo, '반올림 끝전');
      } else P.fo = [];
      const unL = dt && Array.isArray(dt.un) ? dt.un.filter(Array.isArray).map(c => attdIt('un:' + c[0], String(c[0]), num(c[1]) * kf, { sym: String(c[0]), s: L('판 금액 − 그날 가격 평가') })) : [];
      const opL = dt && Array.isArray(dt.op) ? dt.op.filter(Array.isArray).map(c => attdIt('op:' + c[0], String(c[0]), num(c[1]) * kf, { sym: String(c[0]), s: L('기초 잔고 × 그날 가격') })) : [];
      more(unL, 'un', '종'); more(opL, 'op', '종');
      P.un = attdFit(unL, a.un, '원가 미확인 매도', L('원가를 모르는 코인을 판 몫'));
      P.op = attdFit(opL, a.op, '기초 잔고 정정', L('전부터 있던 보유를 이날 원장에 넣음'));
      P.tr = [];
    } else {
      P.rz = []; P.rzf = []; P.fo = []; P.un = []; P.op = [];
      P.tr = attdFit([attdIt('tr', '마감가 대비 체결 차', a.tr, { ico: 'cvt', s: Math.abs(a.fee) >= 0.005 ? '수수료·가스 ' + m(a.fee, { sign: true, compact: true }) + ' 포함' : '' })], a.tr, '반올림 끝전');
    }
    const fl = [];
    if (dt && Array.isArray(dt.fl)) {
      dt.fl.forEach(f => { if (!Array.isArray(f) || f[0] == null) return; const l = String(f[0]), lg = arr(f[2]).filter(Array.isArray);
        fl.push(attdIt('fl:' + l, l, num(f[1]) * kf, { ico: /원화/.test(l) ? 'krw' : 'fl', s: lg.length > 1 ? lg.slice(0, 3).map(g => esc(String(g[0])) + ' ' + m(num(g[1]) * kf, { sign: true, compact: true })).join(' · ') + (lg.length > 3 ? ' 외' : '') : '' })); });
      more(fl, 'fl', '건');
      if (num(dt.rbNew)) fl.push(attdIt('rbNew', 'Rabby 기준 첫 반영', num(dt.rbNew) * kf, { ico: 'rb', s: L('봇이 모르던 보유를 처음 셈 — 시세 아님') }));
      if (num(dt.pv)) fl.push(attdIt('pv', '옛 기록 받는 중인 지갑의 지금 잔고', num(dt.pv) * kf, { ico: 'rb', s: L('첫 대사 전 잔고를 오늘 값에 넣음') }));
    } else arr(isT ? D._todayFlowTop : x.flowTop).forEach(t => { if (Array.isArray(t) && t[0] != null) fl.push(attdIt('fl:' + t[0], String(t[0]), num(t[1]) * kf, { ico: /원화/.test(String(t[0])) ? 'krw' : 'fl' })); });
    if (a.v2 && a.stk) fl.push(attdIt('stk', '스테이킹 보상 → 현물 실현으로', -a.stk, { ico: 'stk', s: L("위 칸 '총 실현'과 같게 실현 줄로 옮김") }));
    P.fl = attdFit(fl, a.fl, '그 밖 작은 이동', L('목록 밖 작은 이동·반올림'));
    const fx = [], R0 = num(x._prev.usdt), R1 = isT ? rate() : num(x.usdt), rr = v => '<span class="pvx">₩' + nf('ko-KR', 0, 2).format(v) + '</span>';
    if (krw) fx.push(attdIt('fxa', '달러 자산 원화 환산', num(x._prev.val) * kf - dayV(x._prev), { ico: 'usd', s: L('전일 마감 달러 자산 × 환율 변화') + (R0 > 0 && R1 > 0 ? ' · USDT ' + rr(R0) + ' → ' + rr(R1) : '') }));
    if (krw || a.v2) {
      const kxs = dt && Array.isArray(dt.kx) && dt.kx.length === 3 ? dt.kx.map(num) : null;
      const KXL = [['kxd', '원화 예수금 환산', '업비트·빗썸 예수금(원화)의 달러 환산 차 — 원화로 보면 안 변하는 몫'], ['kxu', '업비트 원화 입출금 환율 차', '입출금 줄은 그 시각 환율 · 곡선은 그날 마감 환율로 센 차'],
        ['kxb', '빗썸 원화 입출금 환율 차', '입출금 줄은 그 시각 환율 · 곡선은 그날 마감 환율로 센 차']];
      if (kxs) kxs.forEach((v, i) => { if (v) fx.push(attdIt(KXL[i][0], KXL[i][1], v * kf, { ico: 'krw', s: L(KXL[i][2]) })); });
      else if (num(raw.kx)) fx.push(attdIt('kx', '원화 예수금 환산', num(raw.kx) * kf, { ico: 'krw' }));
    }
    if (a.v2) {
      const cs = num(a.rz0) + num(a.lpf) + num(a.stk) - num(a.rz), cf = num(a.fb) - num(a.rzf) - num(a.fo);
      if (cs) fx.push(attdIt('fxs', '현물 실현 환산 차', cs, { ico: 'cvt', s: L(krw ? '실현은 판 시각 환율 · 분해는 그날 마감 환율로 센 차' : '실현 줄과 분해의 센트 반올림 차') }));
      if (cf) fx.push(attdIt('fxf', '선물 정산 환산 차', cf, { ico: 'cvt', s: L(krw ? '선물 정산은 정산 시각 환율 · 분해는 그날 마감 환율로 센 차' : '선물 줄과 분해의 센트 반올림 차') }));
    }
    P.fx = attdFit(fx, a.fx, '반올림 끝전');
    const ot = [];
    if (a.v2) {
      if (dt && Array.isArray(dt.unp) && dt.unp.length) dt.unp.forEach(c => { if (!Array.isArray(c)) return; const w = String(c[2] || '');
        ot.push(attdIt('unp:' + c[0] + ':' + w, String(c[0]) + ' — ' + (w === 'cut' ? '가격 끊김' : w === 'new' ? '가격 생김' : '가격 한쪽 없음'), num(c[1]) * kf, { sym: String(c[0]),
          s: L(w === 'cut' ? '전일 가격이 있던 코인이 그날 가격이 없어 곡선에서 빠짐 — 시세 아님(재료 부족)' : w === 'new' ? '전일 가격이 없던 코인이 그날 가격을 받아 들어옴 — 시세 아님' : '전일·그날 중 한쪽 가격이 없어 시세로 못 나눔') })); });
      else if (a.unp && a.unp.v) ot.push(attdIt('unp', '가격 한쪽 없는 코인 ' + a.unp.n + '종', a.unp.v, { ico: 'unp' }));
      if (dt && Array.isArray(dt.unp) && dt.unp.length) more(ot, 'unp', '종(가격 한쪽 없음)');
      if (a.xr) ot.push(attdIt('xr', a.xca ? '원장 밖 잔고 이월(≈)→실측 차' : '원장 밖 잔고(코인별 기록 없는 몫·LP)', a.xr, { ico: 'lp', s: L('코인별 기록 없는 업비트 미매칭 코인·LP 평가 − 원금 이동') }));
      if (a.rbv) ot.push(attdIt('rbv', 'Rabby 기준 보유 변화', a.rbv, { ico: 'rb', s: L('봇이 추적하지 않는 보유(Rabby 값)의 변화') }));
      if (isT) { const lv = a.delta - (dayV(x) - dayV(x._prev)); if (!isZ(lv)) ot.push(attdIt('live', '실시간 값과 마지막 분해 시각 차', lv, { ico: 'rest', s: L('분해는 마지막 계산 시각 값 · 위 변화는 지금 실시간 값') })); }
      P.oth = attdFit(ot, a.oth, '근사·반올림·마감 스냅숏 시각 차', L('설명 안 된 잔차 — 원장 기장 시각과 마감 스냅숏이 엇갈린 몫·수량 되감기 근사') + (a.np ? ' · <span class="pvx">가격 못 정한 토큰 ' + a.np + '종</span>(그 거래는 0 으로 셈)' : ''));
    } else {
      if (num(a.lp)) ot.push(attdIt('lp', 'LP 예치·회수', a.lp, { ico: 'lp' }));
      if (num(a.xo)) ot.push(attdIt('xo', '원장 밖 잔고', a.xo, { ico: 'lp' }));
      if (a.unp && a.unp.v) ot.push(attdIt('unp', '가격 한쪽 없는 코인 ' + a.unp.n + '종', a.unp.v, { ico: 'unp' }));
      P.oth = attdFit(ot, a.oth, '수량 되감기·근사 차', L('곡선이 되감은 수량과 원장 레그의 차·마감 스냅숏 시각 차·반올림'));
    }
    return P;
  }
  const attdRowsDay = a => [{ key: 'mk', l: '시세', v: a.mk, fold: [] }].concat(attItemsK(a));
  function attdMonKeys(ym) {
    const D = S.D, dim = new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate(), mmP = ym.slice(5, 7) + '-', tISO = isoDay(D.todayKey) || todayISO(), out = [];
    for (let d = 1; d <= dim; d++) {
      if (ym + '-' + pad2(d) > tISO) break;
      const k = mmP + pad2(d);
      if (ymOf(k) === ym && D.dayMap.has(k) && attOf(k)) out.push(k);
    }
    return out;
  }
  const attdMd = k => { const iso = isoDay(k); return (+iso.slice(5, 7)) + '/' + (+iso.slice(8, 10)); };
  function attdItems(q, row, ctx) {
    if (q.mode === 'd') {
      const P = attdParts(q.at, ctx.dets[isoDay(q.at)]);
      if (!P) return [];
      const it = (P[row.key] || []).slice();
      (row.fold || []).forEach(f => { const v = num(ctx.a[f]); if (v) it.push(attdIt('fold:' + f, ATTD_LBL[f] || f, v, { ico: 'fold', fold: 1, s: L0('작아서 나머지에 합친 줄 — 누르면 그 줄 상세'), a: 'attdGo', av: 'd|' + q.at + '|' + f })); });
      return it;
    }
    const by = new Map(), order = [];
    ctx.keys.forEach(k => {
      const P = attdParts(k, ctx.dets[isoDay(k)]);
      if (!P) return;
      (P[row.key] || []).forEach(x => {
        const id = x.rest ? '_rest' : x.id;
        let e = by.get(id);
        if (!e) { e = Object.assign({}, x, { id, v: 0, n: 0, bk: k, bv: 0, tiny: true }); by.set(id, e); order.push(id); }
        e.v += x.v; e.n++;
        if (x.rest === 1) e.tiny = false;
        if (Math.abs(x.v) > Math.abs(e.bv)) { e.bv = x.v; e.bk = k; if (x.a) e.av = x.av; }
      });
    });
    const out = order.map(id => { const e = by.get(id);
      if (id === '_rest') { e.l = e.tiny ? '반올림 끝전' : '그 밖·반올림(날마다)'; e.rest = e.tiny ? 2 : 1; }
      else if (e.more) e.l = '그 밖 작은 항목(날마다 합)';
      e.s = '<span class="pvx">' + e.n + '일</span>' + (e.n > 1 ? ' · 가장 큰 날 <span class="pvx">' + attdMd(e.bk) + '</span> ' + m(e.bv, { sign: true, compact: true }) : ' · <span class="pvx">' + attdMd(e.bk) + '</span>');
      if (e.a === 'attdCoin' || e.a === 'attdRc' || e.a === 'attdFr' || e.a === 'attdLp') e.s += e.a === 'attdCoin' ? '' : ' · 누르면 그날 영수증';
      return e; });
    (row.fold || []).forEach(f => { const v = num(ctx.o[f]); if (v) out.push(attdIt('fold:' + f, ATTD_LBL[f] || f, v, { ico: 'fold', fold: 1, s: L0('작아서 나머지에 합친 줄 — 누르면 그 줄 상세'), a: 'attdGo', av: 'm|' + q.at + '|' + f })); });
    return out;
  }
  function attdDays(q, row, ctx) {
    const cs = [row.key].concat(row.fold || []);
    return ctx.keys.map(k => { const a = attOf(k), v = sum(cs, c => num(a && a[c]));
      return attdIt('d:' + k, heroDayLbl(k), v, { ico: 'day', a: 'attdGo', av: 'd|' + k + '|' + (row.key === 'oth' ? 'oth' : row.key), s: '누르면 그날 ' + esc(row.l) + ' 상세' }); }).filter(x => x.v);
  }
  const attdParse = v => { const p = String(v || '').split('|'); return p.length === 3 && (p[0] === 'd' || (p[0] === 'm' && p[2] !== 'ur')) && ATTD_LBL[p[2]] ? { mode: p[0], at: p[1], key: p[2] } : null; };
  function attdTitle(q) {
    const lb = q.mode === 'm' && q.key === 'mk' ? '시세 변동' : ATTD_LBL[q.key];
    if (q.mode === 'm') return lb + ' · ' + (+q.at.slice(5, 7)) + '월';
    const iso = isoDay(q.at);
    return lb + ' · ' + (S.D && q.at === S.D.todayKey ? '오늘' : (+iso.slice(5, 7)) + '월 ' + (+iso.slice(8, 10)) + '일');
  }
  const attdCoinSub = (it, isT) => { const pp = pxPair(it.p0, it.p1); return (it.pct != null ? '<span class="' + cls(it.pct) + '">' + attPct(it.pct) + '</span>' : '')
    + (it.q != null && it.p0 > 0 && it.p1 > 0 ? (it.pct != null ? ' · ' : '') + attQ(it.q) + '개 · ' + pp[0] + ' → ' + (isT ? '지금 ' : '') + pp[1] : ''); };
  function pxPair(a, b) {
    if (S.hide || !(a >= 1 && b >= 1 && isFinite(a) && isFinite(b))) return [px(a), px(b)];
    const dg = n => (n >= 1000 ? 2 : (nf('en-US', 2, 4).format(n).split('.')[1] || '').length), d = Math.max(dg(a), dg(b));
    return [a, b].map(n => '$' + rw(nf('en-US', d, d).format(n)));
  }
  const attdDs = () => KS(1) * (S.cur === 'USD' ? 100 : rate());
  function attdMoney(v) {
    if (S.hide) return m(v, { sign: true });
    const usd = S.cur === 'USD', n = Math.round(num(v) * attdDs());
    return (n > 0 ? '+' : n < 0 ? '−' : '') + (usd ? '$' : '₩') + rw(nf(usd ? 'en-US' : 'ko-KR', usd ? 2 : 0, usd ? 2 : 0).format(Math.abs(n) / (usd ? 100 : 1)));
  }
  function attdShow(items, want) {
    const ds = attdDs(), out = items.map(x => Object.assign({}, x, { v: Math.round(x.v * ds) / ds })), W = Math.round(num(want) * ds);
    const d = W - sum(out, x => Math.round(x.v * ds));
    if (d) {
      const r = out.find(x => x.rest);
      if (r) r.v = (Math.round(r.v * ds) + d) / ds;
      else out.push(attdIt('_rest', '반올림 끝전', d / ds, { s: esc('항목마다 표시 단위(센트·원)로 반올림한 차'), rest: 2, ico: 'rest' }));
    }
    return out.filter(x => !(x.rest && Math.round(x.v * ds) === 0));
  }
  UI_SHEETS.attd = v => attdSheet(v);
  function attdSheet(v) {
    const D = S.D, q = attdParse(v);
    if (!D || !q) return '<div class="cap">이 줄을 다시 찾지 못했어요</div>';
    const U = S.attdUI || (S.attdUI = { v: '', pg: 0, view: 'it' });
    if (U.v !== v) { U.v = v; U.pg = 0; }
    const ctx = { dets: {}, keys: [], a: null, o: null };
    let rows, st = 'ok', head;
    if (q.mode === 'd') {
      const a = attOf(q.at);
      if (!a) return '<div class="cap">이 날은 분해 기록이 없어요 — 최근 30일만 날마다 분해해요</div>';
      ctx.a = a; ctx.keys = [q.at];
      rows = attdRowsDay(a);
      const iso = isoDay(q.at), isT = q.at === D.todayKey;
      st = attdNeed(iso, iso);
      ctx.dets[iso] = st === 'private' ? undefined : attdCache().days[iso];
      head = (isT ? '오늘' : attdMd(q.at)) + ' 총자산 변화 ' + m(a.delta, { sign: true, compact: true }) + ' 중';
    } else {
      const ym = q.at;
      if (!/^\d{4}-\d{2}$/.test(ym)) return '<div class="cap">이 달을 다시 찾지 못했어요</div>';
      const o = monthAtt(ym);
      if (!o.n) return '<div class="cap">이 달은 자산 변동 분해 기록이 없어요 — 최근 30일만 날마다 분해해요</div>';
      ctx.o = o; ctx.keys = attdMonKeys(ym);
      rows = monthBarRows(o).map(r => ({ key: r[2], l: r[0], v: num(r[1]), fold: r[3] || [] }));
      const lo = isoDay(ctx.keys[0]), hi = isoDay(ctx.keys[ctx.keys.length - 1]);
      st = attdNeed(lo, hi);
      if (st !== 'private') { const C = attdCache(); ctx.keys.forEach(k => { ctx.dets[isoDay(k)] = C.days[isoDay(k)]; }); }
      head = (+ym.slice(5, 7)) + '월 ' + (o.n < o.days ? '<span class="pvx">분해 있는 날 ' + o.n + '일</span> ' : '') + '총자산 변화 ' + m(o.delta, { sign: true, compact: true }) + ' 중';
    }
    const row = rows.find(r => r.key === q.key) || { key: q.key, l: ATTD_LBL[q.key], v: q.mode === 'd' ? num(ctx.a[q.key]) : num(ctx.o[q.key]), fold: [], extra: true };
    const isT = q.mode === 'd' && q.at === D.todayKey;
    const tabs = '<div class="adtabs" role="tablist" aria-label="분해 줄">' + rows.map(r => '<button type="button" role="tab" class="chip' + (r.key === q.key ? ' a' : '') + '" aria-selected="' + (r.key === q.key) + '" data-a="attdGo" data-v="' + esc(q.mode + '|' + q.at + '|' + r.key) + '">' + esc(r.l) + '</button>').join('')
      + (row.extra ? '<button type="button" role="tab" class="chip a" aria-selected="true">' + esc(row.l) + '</button>' : '') + '</div>';
    const wh9 = attdWhat(q.key, isT);
    const sumH = '<div class="adsum"><b class="num ' + clsV(row.v) + '"' + (S.hide || S.rand ? '' : ' title="' + esc(attdMoney(row.v)) + '"') + '>' + m(row.v, { sign: true, compact: true }) + '</b><span class="cap">' + head + (row.extra ? (q.key === 'ur' ? ' · 시세 안의 줄' : ' · 작아서 나머지에 합친 줄') : '')
      + (wh9 ? '<span class="ell" style="display:block" title="' + esc(wh9) + '">' + esc(wh9) + '</span>' : '') + '</span></div>';
    const byDay = q.mode === 'm' && U.view === 'day';
    const seg = q.mode === 'm' ? '<div class="seg adseg" role="group" aria-label="보기">' + [['it', '항목별'], ['day', '날짜별']].map(x => '<button type="button" data-a="attdView" data-v="' + x[0] + '" class="' + ((byDay ? 'day' : 'it') === x[0] ? 'on' : '') + '" aria-pressed="' + ((byDay ? 'day' : 'it') === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' : '';
    const wait = !byDay && st === 'load' && (ATTD_NEED[q.key] || q.key === 'oth') && ctx.keys.some(k => !ctx.dets[isoDay(k)]);
    if (wait) {
      const sk = i => '<div class="adr adsk" aria-hidden="true"><i class="skl" style="width:22px;height:22px;border-radius:50%"></i><span class="adn"><i class="skl" style="width:' + (38 + (i * 23) % 40) + '%"></i><i class="skl" style="width:' + (52 + (i * 17) % 36) + '%;height:9px;margin-top:6px"></i></span><span></span><i class="skl" style="width:64px;justify-self:end"></i><span></span></div>';
      return '<div class="attdp">' + tabs + sumH + '<div class="adlh">' + seg + '<span>목록 받는 중…</span></div><div class="adlist">' + [0, 1, 2, 3, 4, 5].map(sk).join('') + '</div></div>';
    }
    const all = attdShow(byDay ? attdFit(attdDays(q, row, ctx), row.v, '반올림 끝전') : attdItems(q, row, ctx), row.v);
    const main = all.filter(x => !x.fold && !x.rest).sort(byDay ? (x, y) => (x.id < y.id ? 1 : x.id > y.id ? -1 : 0) : (x, y) => Math.abs(y.v) - Math.abs(x.v) || (x.l < y.l ? -1 : x.l > y.l ? 1 : 0));
    const fold = all.filter(x => x.fold), rest = all.filter(x => x.rest && !(x.rest === 2 && isZ(x.v)));
    const gi9 = q.mode === 'd' && q.key === 'rz' && !byDay ? main.findIndex(x => /^gas:/.test(x.id)) : -1;
    const fr9 = q.mode === 'd' && q.key === 'rz' && !byDay ? feeRef(isoDay(q.at), gi9 >= 0 ? main[gi9].v : 0) : null;
    if (fr9 != null) main.splice(gi9 >= 0 ? gi9 + 1 : main.length, 0, attdIt('gasref', '참고 · 매매 가스·수수료', -fr9, { ico: 'gas', ref: 1, s: '<span class="pill g sm">원가·손익에 포함</span> 산 쪽은 원가, 판 쪽은 손익에 이미 들어 있어요 · 합에 안 들어가요' }));
    const vis = main.concat(rest, fold), N = vis.length, nRef = vis.filter(x => x.ref).length;
    const ds = attdDs(), totU = sum(all, x => Math.round(x.v * ds)), wantU = Math.round(row.v * ds), tot = totU / ds, ok = totU === wantU;
    const PG9 = uiPgSz(ATTD_PG), pages = Math.max(1, Math.ceil(N / PG9)), pg = Math.min(Math.max(0, U.pg), pages - 1), lo = pg * PG9, hi = Math.min(N, lo + PG9);
    U.pg = pg;
    const mx = Math.max.apply(null, vis.filter(x => !x.ref).map(x => Math.abs(x.v)).concat([1e-9]));
    const one = it => {
      const ic = it.sym ? icon(it.sym, 'xs', D.symLogo[String(it.sym).toUpperCase()] || {}) : '<span class="ic xs adi" aria-hidden="true">' + String(IC[ATTD_ICO[it.ico]] || IC.info).replace('<svg', '<svg width="12" height="12"') + '</span>';
      const cs = q.mode === 'd' && q.key === 'mk' && it.id.indexOf('c:') === 0 ? attdCoinSub(it, isT) : '', sub = cs && it.s ? cs + ' · ' + it.s : cs || it.s;
      const w = Math.min(100, Math.max(3, Math.abs(it.v) / mx * 100)).toFixed(1);
      const inner = ic + '<span class="adn"><span class="adt">' + esc(it.l) + '</span>' + (sub ? '<span class="ads' + (it.id === U.ux ? ' open' : '') + '">' + sub + '</span>' : '') + '</span>'
        + '<span class="cb2" aria-hidden="true"><i class="' + (it.v >= 0 ? 'p' : 'n') + '" style="width:' + w + '%"></i></span><b class="num ' + clsV(it.v) + '">' + attdMoney(it.v) + '</b>'
        + (it.a ? IC.right.replace('<svg', '<svg class="adcv" width="14" height="14"') : '<span></span>');
      return it.a ? '<button type="button" class="adr" data-a="' + esc(it.a) + '" data-v="' + esc(it.av) + '"' + (it.a === 'attdUx' ? ' aria-expanded="' + (it.id === U.ux) + '"' : '') + '>' + inner + '</button>' : '<div class="adr"' + (it.ref ? ' style="opacity:.6"' : '') + '>' + inner + '</div>';
    };
    let list = '';
    vis.slice(lo, hi).forEach((it, i) => {
      const j = lo + i;
      if (it.fold && (j === 0 || !vis[j - 1].fold)) list += '<div class="adgt">작아서 여기 합친 줄</div>';
      else if (q.key === 'oth' && fold.length && !it.fold && j === 0) list += '<div class="adgt">' + (main.length ? '이름 붙은 몫' : '나머지 몫') + '</div>';
      list += one(it);
    });
    if (!N) list = '<div class="cap adnone">이 줄을 이루는 항목이 없어요(0)</div>';
    const noun = byDay ? '날' : ATTD_NOUN[q.key] || '항목';
    const lh = '<div class="adlh">' + seg + '<span>' + noun + ' <span class="pvx">' + N + '개</span> · ' + (byDay ? '최근 날부터' : '큰 순') + '</span>' + (pages > 1 ? '<span class="num pvx">' + (lo + 1) + '–' + hi + ' / ' + N + '</span>' : '') + '</div>';
    const pager = pages > 1 ? '<div class="adpg"><button type="button" class="btn sm" data-a="attdPg" data-v="-1"' + (pg ? '' : ' disabled') + '>' + IC.left.replace('<svg', '<svg width="14" height="14"') + '이전</button>'
      + '<span class="num pvx">' + (lo + 1) + '–' + hi + ' / ' + N + '</span><button type="button" class="btn sm" data-a="attdPg" data-v="1"' + (pg < pages - 1 ? '' : ' disabled') + '>다음' + IC.right.replace('<svg', '<svg width="14" height="14"') + '</button></div>' : '';
    const ck = '<div class="adck' + (ok ? '' : ' bad') + '">' + (ok ? IC.check : IC.alert) + '<span><span class="pvx">' + (N - nRef) + '개</span>를 모두 더하면 <b class="num ' + clsV(tot) + '">' + attdMoney(tot) + '</b> — ' + (ok ? '위 ' + esc(row.l) + ' 줄과 같아요' : '줄 값과 달라요(새로 계산 중)') + '</span></div>';
    const note = st === 'err' || st === 'old' || st === 'stale' || st === 'private' ? '<div class="adnote">' + IC.info.replace('<svg', '<svg width="14" height="14"') + '<span>' + (st === 'private' ? '금액 가리기·랜덤값에서는 상세 원문을 받지 않아요 — 큰 항목만(끄면 전체)' : st === 'old' ? '서버를 업데이트하면 코인·건별 전체가 보여요 — 지금은 큰 항목만' : st === 'stale' ? '방금 새로 계산됐어요 — 화면이 새 값을 받으면 전체가 보여요(지금은 큰 항목만)' : '자세한 목록을 받지 못해 큰 항목만 보여요') + '</span>' + (st !== 'old' && st !== 'private' ? '<button type="button" class="link" data-a="attdRetry">다시 시도</button>' : '') + '</div>' : '';
    return '<div class="attdp">' + tabs + sumH + lh + '<div class="adlist">' + list + '</div>' + pager + ck + note + '</div>';
  }
  function attdActs() {
    return {
      attdOpen: el => { const v = String(el.dataset.v || ''), q = attdParse(v); if (!q || !S.D) return; S.attdUI = { v, pg: 0, view: (S.attdUI && S.attdUI.view) || 'it' }; uiSheetOpen('attd', v, attdTitle(q), el); },
      attdGo: el => { const v = String(el.dataset.v || ''), q = attdParse(v); if (!q || !S.sheet || S.sheet.k !== 'attd') return; S.sheet.v = v; S.sheet.t = attdTitle(q); vib(); renderOverlay(); },
      attdPg: el => { const U = S.attdUI; if (!U) return; U.pg = Math.max(0, U.pg + (+el.dataset.v || 0)); renderOverlay(); const b = $('#overlay .usheet .adlh'); if (b && b.scrollIntoView) { try { b.scrollIntoView({ block: 'nearest' }); } catch (e) {  } } },
      attdView: el => { const U = S.attdUI; if (!U) return; U.view = el.dataset.v === 'day' ? 'day' : 'it'; U.pg = 0; renderOverlay(); },
      attdRetry: () => { const C = S.attdC; if (C) C.st = {}; renderOverlay(); },
      attdRc: el => { uiSheetCloseThen(() => A.receipt(el)); },
      attdLp: el => { uiSheetCloseThen(() => A.lpGo(el)); },
      attdFr: el => { const v = String(el.dataset.v || ''), i = v.indexOf('|'); uiSheetCloseThen(() => openFutRcpt(i > 0 ? v.slice(0, i) : v, i > 0 ? v.slice(i + 1) : '')); },
      attdUx: el => { const U = S.attdUI, v = String(el.dataset.v || ''); if (!U) return; U.ux = U.ux === v ? '' : v; renderOverlay(); },
      attdCoin: el => { const s = String(el.dataset.v || ''); uiSheetCloseThen(() => { if (s) Promise.resolve(revealAndHighlight('coin:' + s)).then(ok => { if (!ok) toast(s + ' — 지금 보유 목록에 없는 코인이에요(판 코인·값 없는 토큰)'); }); }); },
    };
  }
  function rbLine() { return ''; }
  function habLoad(force) {
    const H = S.hab || (S.hab = { st: '', d: null, at: 0 });
    if (H.st === 'loading' || (!force && H.st && Date.now() - H.at < (H.st === 'building' ? 15000 : 300000))) return;
    if (H.tm) { clearTimeout(H.tm); H.tm = 0; }
    H.st = 'loading';
    H.t0 = Date.now();
    setTimeout(() => { if (H.st === 'loading' && S.tab === 'journal' && S.j.view === 'habits') renderView(); }, 6500);
    fetch('/api/habits', { cache: 'no-store' }).then(r => (r.ok ? r.json() : null)).then(j => { H.d = j && j.ok ? j : null; H.st = H.d ? 'ok' : (j && j.why === 'building' ? 'building' : 'err'); H.at = Date.now(); })
      .catch(() => { H.st = 'err'; H.at = Date.now(); }).then(() => {
        if (H.st === 'building') H.tm = setTimeout(() => { H.tm = 0; if (H.st === 'building' && S.tab === 'journal' && S.j.view === 'habits') habLoad(true); }, 15000);
        if (S.tab === 'journal' && S.j.view === 'habits') renderView();
      });
  }
  const HB_SLOT = ['0~2시', '2~4시', '4~6시', '6~8시', '8~10시', '10~12시', '12~14시', '14~16시', '16~18시', '18~20시', '20~22시', '22~24시'];
  const HB_WD = ['월', '화', '수', '목', '금', '토', '일'];
  function habitsHTML() {
    const H = S.hab || {};
    if (!H.d) {
      habLoad();
      return '<div class="card empty habs"><div class="eic">' + IC.cal + '</div><b>' + (H.st === 'err' ? '습관 리포트를 불러오지 못했어요' : H.st === 'building' ? '기록 색인을 만드는 중이에요' : '습관을 모으는 중…') + '</b>'
        + (H.st === 'building' || (H.st === 'loading' && Date.now() - (H.t0 || Date.now()) > 6000) ? '<div class="cap" style="margin-top:6px">봇이 막 다시 켜지면 기록 색인을 새로 만드느라 1~3분 걸려요 — 다 되면 저절로 보여요</div>' : '')
        + (H.st === 'err' || H.st === 'building' ? '<button class="btn sm" data-a="habRetry" style="margin-top:10px">' + IC.undo + ' 다시 시도</button>' : '') + '</div>';
    }
    if (Date.now() - H.at > 300000) habLoad();
    const d = H.d, avg = d.n ? d.win / d.n * 100 : null;
    if (!d.n) return '<div class="card empty habs"><div class="eic">' + IC.cal + '</div><b>아직 습관을 볼 만큼 매도 기록이 없어요</b>지난 12개월 매도가 쌓이면 시간대·요일·보유 기간별로 보여 드려요</div>';
    const cells = [];
    d.grid.forEach((row, wd) => row.forEach((c, h) => { if (c[0] >= 1) cells.push({ wd, h, n: c[0], w: c[1], r: c[1] / c[0] * 100, pnl: c.length > 2 ? num(c[2]) : null }); }));
    const minN = Math.max(5, Math.round(d.n * 0.02));
    const pool = cells.filter(c => c.n >= minN);
    const worst = pool.slice().sort((a, b) => a.r - b.r || b.n - a.n)[0], bestC = pool.slice().sort((a, b) => b.r - a.r || b.n - a.n)[0];
    const pick = worst && bestC ? (avg - worst.r >= bestC.r - avg ? ['w', worst] : ['b', bestC]) : worst ? ['w', worst] : null;
    const slotTxt = c => (c.h < 3 ? '새벽 ' : c.h < 6 ? '오전 ' : c.h < 9 ? '오후 ' : '밤 ') + HB_SLOT[c.h];
    const head = pick
      ? '<div class="hbh1">' + HB_WD[pick[1].wd] + '요일 ' + esc(slotTxt(pick[1])) + '에 판 것의 이익 비율은 <span class="' + (pick[0] === 'w' ? 'down' : 'up') + '">' + Math.round(pick[1].r) + '%</span>' + (pick[0] === 'w' ? '예요' : '였어요') + '</div>'
        + '<div class="hbh2">전체 평균 ' + Math.round(avg) + '% · 이 시간대 매도 ' + pick[1].n + '묶음 중 ' + (pick[0] === 'w' ? (pick[1].n - pick[1].w) + '묶음이 손실로' : pick[1].w + '묶음이 이익으로') + ' 끝났어요' + (pick[1].pnl != null ? ' · 손익 <span class="' + cls(pick[1].pnl) + '">' + pvm(m(pick[1].pnl, { sign: true, compact: true })) + '</span>' : '') + '</div>'
      : '<div class="hbh1">이익 난 매도 비율 <span class="' + cls(avg - 50) + '">' + Math.round(avg) + '%</span></div>';
    const cell = (c) => {
      if (!c) return '<span class="hbc z"></span>';
      const dv = c.r - avg, a = Math.min(1, Math.abs(dv) / 35);
      const al9 = (0.18 + a * 0.82) * (c.n < 5 ? 0.45 : 1);
      return '<span class="hbc ' + (dv >= 0 ? 'u' : 'd') + (c.n < 5 ? ' lo' : '') + '" style="--a:' + al9.toFixed(2) + (al9 >= 0.6 ? ';color:#fff' : '') + '" title="' + esc(HB_WD[c.wd] + '요일 ' + HB_SLOT[c.h] + ' · 이익 ' + Math.round(c.r) + '% (' + c.w + '/' + c.n + '묶음)' + (c.n < 5 ? ' · 표본 적음' : '')) + '">' + c.n + '</span>';
    };
    const byK = {}; cells.forEach(c => { byK[c.wd + ':' + c.h] = c; });
    let grid = '<div class="hbg"><span></span>' + [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22].map(x => '<span class="hbx">' + x + '</span>').join('');
    for (let wd = 0; wd < 7; wd++) { grid += '<span class="hby">' + HB_WD[wd] + '</span>'; for (let h = 0; h < 12; h++) grid += cell(byK[wd + ':' + h]); }
    grid += '</div>';
    const amt9 = c => (c.pnl != null ? ' <span class="' + cls(c.pnl) + '">' + pvm(m(c.pnl, { sign: true, compact: true })) + '</span>' : '');
    const flat9 = pool.length >= 2 && Math.round(worst.r) === Math.round(bestC.r);
    const fact9 = c => '<b>' + HB_WD[c.wd] + ' · ' + HB_SLOT[c.h] + '</b> 하나 · 이익 ' + Math.round(c.r) + '% · ' + c.n + '묶음' + amt9(c);
    const best2 = pool.length >= 2 && !flat9 && bestC.w > 0 ? '가장 잘 맞는 때 <b class="up">' + HB_WD[bestC.wd] + ' · ' + HB_SLOT[bestC.h] + ' ' + Math.round(bestC.r) + '%</b> · ' + bestC.n + '묶음' + amt9(bestC) : '';
    const worst2 = pool.length < 2 ? '<span class="mut">비교할 시간대가 아직 부족해요 — ' + minN + '묶음 이상 쌓인 칸' + (pool.length ? '은 </span>' + fact9(pool[0]) : '이 아직 없어요</span>')
      : flat9 ? '<span class="mut">시간대마다 이익 비율이 ' + Math.round(bestC.r) + '%로 같아 잘 맞는 때·안 맞는 때는 아직 없어요</span>'
      : worst.w < worst.n ? '가장 안 맞는 때 <b class="down">' + HB_WD[worst.wd] + ' · ' + HB_SLOT[worst.h] + ' ' + Math.round(worst.r) + '%</b> · ' + worst.n + '묶음' + amt9(worst) : '';
    const left = '<section class="card hbcard"><div class="row"><b class="hbt">시간대 × 요일 · 이익 난 매도 비율</b><span class="sp"></span><span class="cap">칸 숫자 = 매도 묶음 수 · 진할수록 평균에서 멀어요 · 5묶음 미만은 흐리게</span></div>' + grid
      + '<div class="hbf">' + [best2, worst2].filter(Boolean).map(x => '<span>' + x + '</span>').join('') + '</div></section>';
    const hs = arr(d.hold).filter(x => num(x.n) > 0 && num(x.cost) > 0).map(x => ({ k: x.k, n: num(x.n), r: num(x.pnl) / num(x.cost) * 100 }));
    const mx = Math.max.apply(null, hs.map(x => Math.abs(x.r)).concat([1]));
    const hold = '<section class="card hbcard"><b class="hbt">보유 기간별 평균 수익률</b>' + (hs.length ? hs.map(x => '<div class="hbr"><span class="k">' + esc(x.k) + '</span><span class="bar"><i class="' + (x.r >= 0 ? 'u' : 'd') + '" style="width:' + Math.max(3, Math.abs(x.r) / mx * 100).toFixed(1) + '%"></i></span><b class="num ' + cls(x.r) + '">' + pctS(x.r, 1) + '</b><span class="n num">' + x.n + '</span></div>').join('')
      : '<div class="cap">보유 기간을 알 수 있는 매도가 아직 없어요</div>') + '<div class="cap">원가 대비 · 기간 = 그 코인 첫 매수부터 판 날까지 · 오른쪽 = 매도 묶음 수</div></section>';
    const nx = arr(d.next), pu = nx[1] ? nx[0] / nx[1] * 100 : null, C = 2 * Math.PI * 38;
    const ring = pu == null ? '' : '<section class="card hbcard hbring"><svg width="96" height="96" viewBox="0 0 96 96" aria-hidden="true"><circle cx="48" cy="48" r="38" fill="none" stroke="var(--line2)" stroke-width="10"/><circle cx="48" cy="48" r="38" fill="none" stroke="var(--warn)" stroke-width="10" stroke-linecap="round" stroke-dasharray="' + (C * pu / 100).toFixed(1) + ' ' + C.toFixed(1) + '" transform="rotate(-90 48 48)"/><text x="48" y="54" text-anchor="middle" class="rtx">' + Math.round(pu) + '%</text></svg>'
      + '<div class="rt"><b class="hbt">판 다음 날 더 오른 비율</b><span>10번 중 ' + Math.round(pu / 10) + '번은 다음 날 마감가가 판 값보다 1% 넘게 높았어요</span><span class="cap">시세 기록 있는 ' + nx[1] + '묶음 · 다음 날 평균 ' + pctS(num(d.nextAvg), 1) + '</span></div></section>';
    return '<div class="habs pvx"><div class="hbhd"><div class="cap">나의 매매 습관 · 지난 12개월 · 매도 ' + d.n + '묶음</div>' + head + '</div>'
      + '<div class="hbgrid">' + left + '<div class="hbside">' + hold + ring + '</div></div>'
      + '<div class="cap hbnote">묶음 = 그날 그 코인 매도(차익 영수증과 같은 단위) · 시각 = 그날 그 코인 가장 큰 매도 · 보유 기간 = 첫 매수부터 실제 매도 시각까지'
      + (d.excl && (num(d.excl.stable) || num(d.excl.quar)) ? ' · 스테이블 환전 ' + num(d.excl.stable) + '묶음' + (num(d.excl.quar) ? ' · 격리 ' + num(d.excl.quar) + '묶음' : '') + '은 뺐어요' : '')
      + (d.cov && d.cov.next != null ? ' · 다음 날 시세 확인 ' + Math.round(num(d.cov.next) * 100) + '%' + (d.cov.pxAt ? ' · 시세 기준 ' + esc(String(d.cov.pxAt).slice(5).replace('-', '/')) : '') : '') + '</div></div>';
  }
  const BENCH_K = ['btc'];
  const benchSet = () => new Set(String(LS.get('tj_v2_bench') || '').split(',').filter(k => BENCH_K.indexOf(k) >= 0));
  const benchOn = k => (k ? benchSet().has(k) : benchSet().size > 0);
  const benchAt = (B, sk) => (B.hAt && B.hAt[sk] != null ? B.hAt[sk] : num(B.at));
  function benchLoad(force, since) {
    const B = S.bench || (S.bench = { st: '', d: null, at: 0, h: {}, hs: {}, hAt: {} });
    B.h = B.h || {}; B.hs = B.hs || {}; B.hAt = B.hAt || {};
    const sk = /^\d{4}-\d{2}-\d{2}$/.test(since || '') ? since : '', at = benchAt(B, sk);
    if (B.st === 'loading' || (B.hs[sk] === 'loading') || (!force && B.hs[sk] !== 'err' && B.st && Date.now() - at < 600000 && (!sk || B.h[sk]))) return;
    if (!force && B.hs[sk] === 'err' && Date.now() - at < 60000) return;
    B.st = 'loading'; B.hs[sk] = 'loading';
    fetch('/api/bench' + (sk ? '?since=' + sk : ''), { cache: 'no-store' }).then(r => (r.ok ? r.json() : null)).then(j => { const nd = j && j.ok && j.px && typeof j.px === 'object' ? j : null;
      if (nd) { B.d = nd; B.h[sk] = { hold: nd.hold || {}, holdCov: nd.holdCov, rows: arr(nd.rows), nRows: num(nd.nRows), pxAt: nd.pxAt || null, since: nd.since || sk }; const ks = Object.keys(B.h); if (ks.length > 8) { delete B.h[ks[0]]; delete B.hAt[ks[0]]; } }
      B.st = B.d ? 'ok' : 'err'; B.hs[sk] = nd ? 'ok' : 'err'; B.at = B.hAt[sk] = Date.now(); })
      .catch(() => { B.st = B.d ? 'ok' : 'err'; B.hs[sk] = 'err'; B.at = B.hAt[sk] = Date.now(); }).then(() => { if (S.D && S.tab === 'dash') renderAuto(); });
  }
  function benchVals(pts) {
    const B = S.bench, since0 = pts && pts.length ? (isoDay(pts[0].date) || String(pts[0].date)) : '';
    if (!B || !B.d) { benchLoad(false, since0); return null; }
    const exp9 = Date.now() - benchAt(B, since0) >= 600000;
    if (exp9 || (B.hs && B.hs[since0] === 'err') || (B.d.since && !(B.h && B.h[since0]))) benchLoad(exp9, since0);
    const hb = (B.h && B.h[since0]) || (B.d.hold && !B.d.since ? { hold: B.d.hold, holdCov: B.d.holdCov, rows: arr(B.d.rows), nRows: num(B.d.nRows), pxAt: B.d.pxAt || null, since: '' } : null);
    const D = S.D, px = B.d.px || {}, hd = hb ? hb.hold || {} : {}, keys = Object.keys(px).sort(), tk = D.todayKey;
    let ki = 0, lastPx = null, u = null, neg = 0;
    const priceAt = iso => { while (ki < keys.length && keys[ki] <= iso) { lastPx = num(px[keys[ki]]); ki++; } return lastPx; };
    const btc = [], hold = [];
    const flowOk = !pts.some((p, i) => i > 0 && p.row && p.row._hist && (p.row.flow == null || num(p.row.nofx)));
    pts.forEach(p => {
      const isT = p.date === tk, iso = isoDay(p.date) || p.date;
      const usd = isT ? num(D.total) : num(p.row && p.row.val), f = usd > 0 ? p.val / usd : null;
      const pr = isT ? (num(B.d.now) > 0 ? num(B.d.now) : priceAt(iso)) : priceAt(iso);
      if (flowOk && pr > 0 && f != null) {
        const flow = isT ? num(D._todayFlow) : (p.row && p.row.flow != null ? num(p.row.flow) : 0);
        u = u == null ? usd / pr : u + flow / pr;
        if (u < 0) neg++;
        btc.push(u * pr * f);
      } else btc.push(null);
      hold.push(hb && f != null && hd[iso] != null ? p.val + num(hd[iso]) * f : (hb && f != null && Object.keys(hd).length ? p.val : null));
    });
    return { btc: btc.some(v => v != null) ? btc : null, hold: hb && Object.keys(hd).length && hold.some(v => v != null) ? hold : null, btcNeg: neg, hb, since: since0 };
  }
  const benchPct = (arr9, h) => { if (arr9.length < 2 || arr9.some(v => v == null)) return null; return retPct(arr9[0], arr9[arr9.length - 1], h.flowSum); };
  function benchCards(pts, h, bv) {
    if (!bv || !benchOn()) return '';
    if (h.histFlowMiss || h.nofxN) return '<div class="cap bnote">' + (h.histFlowMiss ? '과거 입출금 계산이 끝나면 비교 결과를 보여 드려요' : '그날 환율 기록이 없는 원화 입출금이 있어 이 기간 비교 결과는 생략했어요') + '</div>';
    const act = h.first && h.first.val ? retPct(h.first.val, h.first.val + num(h.adj) + num(h.flowSum), h.flowSum) : null;
    const pb = benchOn('btc') && bv.btc ? benchPct(bv.btc, h) : null, ph = benchOn('hold') && bv.hold ? benchPct(bv.hold, h) : null;
    const main = pb != null ? ['btc', pb, 'BTC 만 들고 있었다면', '같은 날 같은 돈으로 BTC 매수 가정'] : ph != null ? ['hold', ph, '판 코인을 계속 들고 있었다면', '판 날의 수량을 그대로 들고 있었다면'] : null;
    if (act == null || !main) return '';
    const dp = act - main[1], other = pb != null && ph != null ? ' · 안 팔았다면 대비 ' + pctS(act - ph, 1).replace('%', '%p') : '';
    const card = (cl, lab, v, sub, sw) => '<div class="bcard ' + cl + '"><div class="bl">' + sw + esc(lab) + '</div><div class="bv num">' + pctS(v, 1) + '</div><div class="bs">' + esc(sub) + '</div></div>';
    const hb9 = bv.hb, covT = ph != null && hb9 && hb9.holdCov != null ? ' · 판 대금 시세 확인 ' + Math.round(num(hb9.holdCov) * 100) + '%' + (hb9.pxAt ? ' · 시세 ' + String(hb9.pxAt).slice(5).replace('-', '/') + ' 기준' : '') : '';
    const nb = hb9 && ph != null ? num(hb9.nRows) || arr(hb9.rows).length : 0;
    const foot = (pb != null && bv.btcNeg ? 'BTC 비교: 출금이 비교 잔고보다 컸던 ' + bv.btcNeg + '일은 음수(빌린 셈)로 계산했어요(0 에서 멈추지 않게)' : '')
      + (nb ? (pb != null && bv.btcNeg ? ' · ' : '') + '<button type="button" class="link" data-a="benchRows" data-v="' + esc(bv.since || '') + '">안 팔았다면 · 판 것 ' + nb + '건 하나씩 보기</button>' : '');
    return '<div class="bcards pvx">' + card('act', '내 실제 매매', act, '입출금 뺀 순수익률', '<i class="bsw act"></i>')
      + card(main[0], main[2], main[1], main[3] + (main[0] === 'hold' ? covT : ''), '<i class="bsw ' + main[0] + '"></i>')
      + '<div class="bcard win ' + (dp >= 0 ? 'w' : 'l') + '"><div class="bl">' + (dp >= 0 ? '내 매매가 이겼어요' : '들고만 있는 게 나았어요') + '</div><div class="bv num">' + pctS(dp, 1).replace('%', '%p') + '</div><div class="bs">' + esc((main[0] === 'btc' ? 'BTC 보유 대비' : '판 코인 보유 대비') + other + (main[0] === 'btc' ? covT : '')) + '</div></div></div>'
      + (foot ? '<div class="cap bnote pvx">' + foot + '</div>' : '');
  }
  UI_SHEETS.bestm = () => {
    const ws = bestWindows(), md9 = iso => (+iso.slice(5, 7)) + '/' + (+iso.slice(8, 10));
    const row = w => '<div class="bmr">' + '<span class="w num pvx">' + esc(md9(w.from)) + '~' + esc(md9(w.to)) + '</span>'
      + (w.best ? '<button type="button" class="bmb' + (S.bestPick === w.best.iso ? ' on' : '') + '" data-a="bestPick" data-v="' + esc(w.best.iso) + '"><b class="num pvx">' + esc(heroDayLbl(w.best.iso)) + '</b><span class="s">' + esc(w.best.sym || '') + (w.best.more ? ' 등' : '') + '</span><span class="num up">' + m(w.best.v, { sign: true, compact: true }) + '</span>' + IC.right + '</button>'
        : '<span class="bmn mut">거래 없음</span>') + '</div>';
    const head = '<div class="cap" style="margin-bottom:8px">' + (ws.length > 1 ? '오늘부터 거꾸로 한 달씩 <span class="pvx">' + ws.length + '칸</span> · ' : '') + '그날 실현(현물 + 선물) 가장 큰 날 · 고르면 차트에 표시하고 그날로 가요</div>';
    return head + '<div class="bml">' + uiPaged('bestm', ws, w => row(w), { unit: '칸' }) + '</div>';
  };
  UI_SHEETS.benchRows = since => {
    const hb = S.bench && S.bench.h && S.bench.h[since];
    if (!hb) return '<div class="cap">불러오는 중…</div>';
    const rows = arr(hb.rows), n = num(hb.nRows) || rows.length;
    const md9 = iso => String(iso || '').slice(2).replace(/-/g, '.');
    const head = '<div class="cap" style="margin-bottom:8px">' + esc(md9(hb.since)) + '부터 판 것 · 지금 가격 = 같은 자산 묶음의 마지막 시세(' + (hb.pxAt ? esc(md9(hb.pxAt)) + ' 기준' : '없음') + ') · 판 대금 시세 확인 ' + Math.round(num(hb.holdCov) * 100) + '%</div>';
    const body = rows.map(r => '<div class="bkr"><span class="d num pvx">' + esc(md9(r.d)) + '</span><b>' + esc(r.sym) + '</b><span class="num">' + px(num(r.sp)) + '</span><span class="num">' + (r.now != null ? px(num(r.now)) : '<span class="mut pvx">' + (r.st === 'nogrp' ? '묶음 모름' : '시세 없음' + (r.lastPx ? ' · ' + esc(md9(r.lastPx)) + '까지' : '')) + '</span>') + '</span>'
      + '<span class="num ' + (r.diff != null ? cls(r.diff) : 'mut') + '">' + (r.diff != null ? m(num(r.diff), { sign: true, compact: true }) : '—') + '</span></div>').join('');
    return head + '<div class="bkt"><div class="bkr h"><span>판 날</span><span>코인</span><span>판 가격</span><span>지금 가격</span><span>안 팔았다면</span></div>' + (body || '<div class="cap">이 기간엔 판 것이 없어요</div>') + '</div>'
      + (n > rows.length ? '<div class="cap" style="margin-top:8px">최근 <span class="pvx">' + rows.length + '건</span>만 · 전체 <span class="pvx">' + n + '건</span></div>' : '');
  };
  function benchLeg() {
    const B = S.bench || {}, chip = (k, lab, ic) => '<button type="button" class="bchip ' + k + (benchOn(k) ? ' on' : '') + '" data-a="benchTog" data-v="' + k + '" aria-pressed="' + benchOn(k) + '">' + ic + esc(lab) + '</button>';
    const st = benchOn() && !B.d && (B.st === 'loading' || !B.st) ? '<span class="cap">시세 불러오는 중…</span>' : benchOn() && B.st === 'err' ? '<span class="cap">비교 시세를 불러오지 못했어요</span>' : '';
    return '<span class="bchips">' + chip('btc', 'BTC 만 들고 있었다면', '<i class="bsw btc"></i>') + st + '</span>';
  }
  function chartSVG(pts, h, best, bestChip) {
    const D = S.D;
    const W = 700, H = 124, n = pts.length;
    const vals = pts.map(p => p.val);
    const bv = benchOn() ? benchVals(pts) : null, bb = benchOn('btc') && bv ? bv.btc : null, bh = benchOn('hold') && bv ? bv.hold : null;
    const vAll = vals.concat(bb ? bb.filter(v => v != null) : [], bh ? bh.filter(v => v != null) : []);
    let lo = Math.min.apply(null, vAll), hi = Math.max.apply(null, vAll);
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const kr = (S.cur === 'USD' ? 1 : rate()) * KS(1);
    const niceStep = raw => { const e = Math.pow(10, Math.floor(Math.log10(raw))); for (const f of [1, 2, 2.5, 5, 10]) if (f * e >= raw) return f * e; return 10 * e; };
    const axA = Math.max(Math.abs(lo), Math.abs(hi)) * kr, axRes = S.cur === 'USD' ? (axA >= 1e6 ? 1e4 : axA >= 1e4 ? 100 : axA >= 100 ? 1 : 0.01) : (axA >= 1e8 ? 1e6 : axA >= 1e4 ? 1e4 : 1);
    const step = Math.max(niceStep((hi - lo) * kr / 3), axRes);
    const t0 = Math.floor(lo * kr / step + 1e-9) * step, t1 = Math.ceil(hi * kr / step - 1e-9) * step;
    const ticks = []; for (let v = t1; v >= t0 - step * 1e-6 && ticks.length < 8; v -= step) ticks.push(v / kr);
    lo = t0 / kr; hi = t1 / kr;
    const pad = (hi - lo) * 0.06;
    lo -= pad; hi += pad;
    const X = i => i / (n - 1) * W, Y = v => H - (v - lo) / (hi - lo) * H;
    const line = pts.map((p, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(p.val).toFixed(1)).join(' ');
    const apSeg = i => pts[i].ap > 0 || pts[i - 1].ap > 0;
    const runs = []; let r0 = -1;
    for (let i = 1; i < n; i++) { if (apSeg(i)) { if (r0 < 0) r0 = i - 1; } else if (r0 >= 0) { runs.push([r0, i - 1]); r0 = -1; } }
    if (r0 >= 0) runs.push([r0, n - 1]);
    const apN = pts.filter(p => p.ap > 0).length;
    const up = pts[n - 1].val >= pts[0].val;
    const col = up ? 'var(--up)' : 'var(--down)';
    const ex = X(n - 1) / W * 100, ey = Y(pts[n - 1].val) / H * 100;
    let len = 0; for (let i = 1; i < n; i++) len += Math.hypot(X(i) - X(i - 1), Y(pts[i].val) - Y(pts[i - 1].val));
    S._chart = { pts, lo, hi, n, bench: bb || bh ? { btc: bb, hold: bh } : null };
    const bpath = a9 => { let d9 = '', st9 = false; if (!a9) return ''; a9.forEach((v, i) => { if (v == null) { st9 = false; return; } d9 += (st9 ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1) + ' '; st9 = true; }); return d9; };
    const bline = bpath(bb), hline = bpath(bh);
    const ck = S.chartDays + ':' + n;
    const draw = S.anim.chartKey !== ck;
    S.anim.chartKey = ck;
    const frs = ticks.map(v => (hi - v) / (hi - lo));
    const grid = ticks.map((v, i) => '<span class="gl num" style="top:' + (frs[i] * 100).toFixed(2) + '%">' + m(v, { compact: true }).replace(/^₩|^\$/, S.cur === 'USD' ? '$' : '') + '</span>').join('');
    const gridLines = frs.map(fr => '<line x1="0" x2="' + W + '" y1="' + (H * fr).toFixed(2) + '" y2="' + (H * fr).toFixed(2) + '" stroke="var(--line)" stroke-width="1" vector-effect="non-scaling-stroke"/>').join('');
    const bands = runs.map(r => '<rect class="apband" x="' + X(r[0]).toFixed(1) + '" y="0" width="' + Math.max(1, X(r[1]) - X(r[0])).toFixed(1) + '" height="' + H + '" style="fill:var(--accent)" fill-opacity=".06"/>').join('');
    const tot9 = Math.abs(num(pts[n - 1].val)), thr9 = Math.max(0.01 * tot9, 1e7 / rate()), flo9 = 0.003 * tot9;
    const dOf = i => (pts[i].delta != null && isFinite(pts[i].delta) ? num(pts[i].delta) : num(pts[i].val) - num(pts[i - 1].val));
    const cand9 = []; for (let i = 1; i < n - 1; i++) cand9.push([i, dOf(i)]);
    cand9.sort((a0, b0) => Math.abs(b0[1]) - Math.abs(a0[1]));
    let mv9 = cand9.filter(c9 => Math.abs(c9[1]) >= thr9).slice(0, 6);
    if (mv9.length < 3) mv9 = mv9.concat(cand9.filter(c9 => Math.abs(c9[1]) < thr9 && Math.abs(c9[1]) >= flo9).slice(0, 3 - mv9.length));
    const bi = best ? pts.findIndex(p => (isoDay(p.date) || p.date) === best.iso) : -1;
    const pki = S.bestPick ? pts.findIndex(p => (isoDay(p.date) || p.date) === S.bestPick) : -1;
    const mvTip = (i, d) => {
      const k = pts[i].date, a = attOf(k), dv = a ? a.delta : d;
      const rz = KV(num(D.realized[k]), D.hasKrw ? D.realizedK[k] : null);
      const V = v => '<b class="' + cls(v) + '">' + m(v, { sign: true, compact: true }) + '</b>';
      const rows = [];
      if (a) {
        const mv = attMovers(a, 2, false);
        rows.push('시세 ' + V(a.mk) + (mv ? ' <span class="mut">(' + esc(mv) + ')</span>' : ''));
        attItems(a).forEach(x => rows.push(x[0] + ' ' + V(x[1])));
      }
      if (Math.abs(rz) >= 0.005 && !(a && a.v2)) rows.push('그날 실현 ' + V(rz));
      const r9 = pts[i].row || {};
      if (!a && r9._hist && r9.flow != null) { const fl = num(dayFlowV(r9)); rows.push('시장 변동 ' + V(d - fl)); rows.push('입출금 ' + V(fl) + (arr(r9.flowTop).length ? ' <span class="mut">(' + esc(arr(r9.flowTop).slice(0, 2).map(t => t[0]).join(' · ')) + ')</span>' : '')); }
      return '<span class="mvtip num" role="tooltip"><span class="mt">' + esc(heroDayLbl(k)) + ' ' + (a && a.ap ? '≈ ' : '') + V(dv) + '</span>'
        + (rows.length ? rows.map(x => '<span class="mr">' + x + '</span>').join('') : '<span class="mr mut">분해 기록 없음 — 그날 기록에서 확인</span>') + '</span>';
    };
    const mxd9 = Math.max.apply(null, mv9.map(c9 => Math.abs(c9[1])).concat([1e-9]));
    const marks = mv9.map(c9 => { const i = c9[0], d = c9[1], xp = X(i) / W * 100, yp = Y(pts[i].val) / H * 100, ms = 10 + 20 * Math.sqrt(Math.abs(d) / mxd9);
      return '<button class="mvd' + (xp < 22 ? ' l' : xp > 78 ? ' r' : '') + (yp < 45 ? ' b' : '') + (i === bi ? ' best' : '') + '" data-a="mvDot" data-v="' + esc(pts[i].date) + '" style="left:' + xp.toFixed(2) + '%;top:' + yp.toFixed(2) + '%;--ms:' + ms.toFixed(1) + 'px;--mc:' + (d >= 0 ? 'var(--up)' : 'var(--down)') + '" aria-label="' + esc(heroDayLbl(pts[i].date) + ' 전일 대비 ' + m(d, { sign: true, compact: true }) + ' — 왜 변했는지 · 그날 기록') + '">' + mvTip(i, d) + '</button>'; }).join('');
    const mvSet = new Set(mv9.map(c9 => c9[0]));
    const bx = bi >= 0 ? X(bi) / W * 100 : 0, by = bi >= 0 ? Y(pts[bi].val) / H * 100 : 0;
    const bmark = bi >= 0 ? (mvSet.has(bi) ? '' : '<span class="bdot" style="left:' + bx.toFixed(2) + '%;top:' + by.toFixed(2) + '%;background:var(--up)"></span>')
      + (pki >= 0 && pki !== bi ? '<span class="bdot pick" style="left:' + (X(pki) / W * 100).toFixed(2) + '%;top:' + (Y(pts[pki].val) / H * 100).toFixed(2) + '%"></span>' : '')
      + (bi < n - 4 ? '<span class="blab num" style="left:' + Math.min(88, Math.max(10, bx)).toFixed(2) + '%;top:' + by.toFixed(2) + '%">' + esc(heroDayLbl(best.k).replace(/ \(.\)$/, '')) + ' · 최고의 날' + (best.sym ? ' ' + esc(best.sym) : '') + ' <span class="up">' + m(best.v, { sign: true, compact: true }) + '</span></span>' : '') : '';
    const isT = h && h.today != null && pts[n - 1].date === D.todayKey;
    const tcol = isT ? (h.disc || h.split ? 'mut' : cls(h.today)) : '';
    const tb = isT ? '<span class="tbadge num ' + tcol + '" style="top:' + (ey < 50 ? 'calc(' + ey.toFixed(2) + '% + 16px)' : 'calc(' + ey.toFixed(2) + '% - 16px)') + ';' + (ey < 50 ? '' : 'transform:translateY(-100%)') + '">오늘 ' + (h.ap ? '≈ ' : '') + m(h.today, { sign: true, compact: true }) + ' <small>' + pctS(h.todayPct, 2) + '</small></span>' : '';
    const xi = n <= 7 ? pts.map((_, i) => i) : [0, 1, 2, 3, 4].map(k => Math.round(k * (n - 1) / 4)).filter((v, i, a0) => a0.indexOf(v) === i);
    const xlab = xi.map(i => '<span>' + esc((isoDay(pts[i].date) || pts[i].date).slice(5)) + '</span>').join('');
    const legBits = [];
    if (apN) legBits.push('<span title="그날 시세 기록이 없는 토큰·거래소 통화는 처음 계산한 시각의 시세로, 원장 밖 잔고는 지금 값으로 이월해 평가했어요">옅은 띠 = 근사(' + apN + '일' + (S.mobile ? ' · 그날 시세 기록 없는 자산은 추정 시세' : '') + ')</span>');
    legBits.push(benchLeg());
    if (mv9.length) legBits.unshift('<span class="lg9" title="보이는 기간에서 전일 대비 변화가 큰 날 ' + mv9.length + '일 — 점을 가리키면(모바일은 누르면) 시세·입출금·매매·실현으로 나눠 보여요"><span class="lgd"><i class="u"></i>크게 오른 날</span><span class="lgd"><i class="d"></i>크게 내린 날</span><span>점 크기 = 그날 움직인 금액</span></span>');
    return '<div>' + benchCards(pts, h, bv) + '<div class="chart' + (draw ? ' draw' : '') + '" id="chart" role="group" aria-label="' + n + '일 총자산 추이 (누르면 그날 기록)" style="color:' + col + '">'
      + '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="' + n + '일 총자산 추이, ' + esc(m(pts[0].val, { compact: true })) + '에서 ' + esc(m(pts[n - 1].val, { compact: true })) + '"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:' + col + ';stop-opacity:.16"/><stop offset="1" style="stop-color:' + col + ';stop-opacity:0"/></linearGradient></defs>'
      + bands + gridLines + '<path class="area" d="' + line + ' L' + W + ' ' + H + ' L0 ' + H + ' Z" fill="url(#cg)"/>'
      + '<path class="ln" d="' + line + '" fill="none" style="stroke:' + col + ';--len:' + Math.ceil(len) + '" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
      + (hline ? '<path class="bln hold" d="' + hline + '" fill="none" stroke-width="1.6" stroke-dasharray="2 5" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' : '')
      + (bline ? '<path class="bln btc" d="' + bline + '" fill="none" stroke-width="2" stroke-dasharray="6 6" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' : '') + '</svg>'
      + (runs.length ? '<span class="apl">근사 구간 · 그날 시세 기록 없는 자산은 추정 시세</span>' : '')
      + grid + marks + bmark + tb
      + '<span class="end" style="left:' + ex + '%;top:' + ey + '%;background:' + col + '"></span>'
      + '<span class="guide hidden"></span><span class="hdot hidden" style="background:' + col + '"></span></div>'
      + '<div class="chart-x num">' + xlab + '</div>'
      + '<div class="chart-foot"><span class="cap mkleg">' + legBits.join('<span class="dv">·</span>') + (S.mobile && bestChip ? bestChip : '') + '</span><span class="sp"></span>' + (S.mobile ? '' : bestChip || '') + '<span class="hide-sm num hilo">최고 ' + m(Math.max.apply(null, vals), { compact: true }) + ' · 최저 ' + m(Math.min.apply(null, vals), { compact: true }) + '</span></div></div>';
  }
  function bindChart() {
    const el = $('#chart');
    if (!el || !S._chart) return;
    const c = S._chart;
    const guide = $('.guide', el), dot = $('.hdot', el);
    const big = $('#heroBig'), chg = $('#heroChg'), when = $('#heroWhen');
    const at = ev => { const r = el.getBoundingClientRect(); const x = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) / r.width; return Math.max(0, Math.min(c.n - 1, Math.round(x * (c.n - 1)))); };
    let orig = null;
    const show = ev => {
      const i = at(ev), p = c.pts[i];
      if (!orig) orig = { big: big.innerHTML, chg: chg.innerHTML, title: big.getAttribute('title') };
      const xp = i / (c.n - 1) * 100, yp = (1 - (p.val - c.lo) / (c.hi - c.lo)) * 100;
      guide.style.left = xp + '%'; dot.style.left = xp + '%'; dot.style.top = yp + '%';
      guide.classList.remove('hidden'); dot.classList.remove('hidden');
      const u = S.D.usdt[p.date] || {};
      const isStep = S.D.steps.indexOf(p.date) >= 0, isSplit = p.date === S.D.todayKey ? !!S.D._todaySplit : !!(p.row && p.row.split);
      big.textContent = (p.ap > 0 ? '≈ ' : '') + m(p.val, { compact: S.mobile });
      if (orig.title != null) big.setAttribute('title', (p.ap > 0 ? '≈ ' : '') + m(p.val));
      if (when) when.textContent = '· ' + (d9 => /^\d{4}-\d{2}-\d{2}$/.test(d9) ? (+d9.slice(5, 7)) + '월 ' + (+d9.slice(8)) + '일' : d9)(String(isoDay(p.date) || p.date)) + (p.dow ? ' (' + p.dow + ')' : '');
      const fl9 = p.date === S.D.todayKey ? S.D._todayFlow : dayFlowV(p.row), ft9 = p.date === S.D.todayKey ? S.D._todayFlowTop : (p.row || {}).flowTop;
      TJDOM.set(chg, (p.delta != null ? '<span class="' + (isStep || isSplit ? 'mut' : cls(p.delta)) + '">전일 대비 ' + m(p.delta, { sign: true }) + (isSplit && fl9 != null ? ' <small>' + (attOf(p.date) ? '<span class="nw">· 입출금 ' + m(num(fl9), { sign: true, compact: true }) + '</span>' : flowSplit(p.delta, fl9, ft9, true)) + '</small>' : (isStep ? ' <small>· 입출금 포함</small>' : '')) + '</span>' : '<span class="mut">첫날</span>')
        + (u.usdt ? '<span class="hov">USDT ₩' + nf('ko-KR').format(num(u.usdt)) + (u.kimp != null ? ' · 김프 ' + pctS(num(u.kimp), 2) : '') + '</span>' : '')
        + (p.ap > 0 ? '<span class="hov">근사 · 추정 평가 ' + m(p.ap, { compact: true }) + ' 포함</span>' : ''));
      if (c.bench) {
        const bb9 = c.bench.btc && c.bench.btc[i], bh9 = c.bench.hold && c.bench.hold[i];
        TJDOM.insert(chg, 'beforeend', (bb9 != null ? ' <span class="hov bhov btc">BTC 만 ' + m(bb9, { compact: true }) + '</span>' : '') + (bh9 != null ? ' <span class="hov bhov hold">안 팔았다면 ' + m(bh9, { compact: true }) + '</span>' : ''));
      }
    };
    const hide = () => {
      guide.classList.add('hidden'); dot.classList.add('hidden');
      if (orig) { TJDOM.set(big, orig.big); TJDOM.set(chg, orig.chg); if (orig.title != null) big.setAttribute('title', orig.title); orig = null; }
      if (when) when.textContent = '';
    };
    el.addEventListener('mousemove', show);
    el.addEventListener('touchstart', show, { passive: true });
    el.addEventListener('touchmove', show, { passive: true });
    el.addEventListener('touchend', hide);
    el.addEventListener('mouseleave', hide);
    el.addEventListener('click', ev => { if (ev.target && ev.target.closest && ev.target.closest('.mvd')) return;
      const p = c.pts[at(ev)]; if (p && !S.mobile) openDay(p.date); });
  }
  function attnItems() {
    const D = S.D, it = [];
    const pendVisUsd = sum(D.pendVis.filter(p => p._cat !== 'unkh'), p => num(p.usd));
    if (D.hasOF && D.ofPendN) it.push({ ico: 'w', col: 'var(--warn)', i: IC.send, t: '외부 전송 확인', n: D.ofPendN + '곳', d: (D.ofBrU.length ? '브릿지 미추적 ' + D.ofBrU.length + '곳 포함(금액은 나머지 ' + D.ofPend.length + '곳 순유출) · ' : '') + '내 지갑 / 거래소 / 외부 유출 중 골라 주세요', usd: num(D.ofPendUsd), go: '확인하기', a: 'go', k: 'outflows' });
    if (D.bcConfirmed.length) it.push({ ico: 'w', col: 'var(--warn)', i: IC.scale, t: '잔고 불일치', n: D.bcConfirmed.length + '건', d: '원장과 온체인 실잔고가 달라요', usd: sum(D.bcConfirmed, x => Math.abs(num(x.diffUsd))), go: '대조하기', a: 'goPend', k: 'bal' });
    const unkhN = D.unkhSymN;
    if (unkhN || D.unkRestUsd >= 1) it.push({ ico: 'w', col: 'var(--warn)', i: IC.coin, t: '원가 미확인 보유', n: unkhN + '종', d: (D.unkhFbN ? '평균가 대체 ' + D.unkhFbN + '건 포함 · ' : '') + '평가손익에서 빠져 있어요' + (D.unkRestUsd >= 1 ? ' · 목록 밖 소액 ' + D.unkRestN + '종 ' + m(D.unkRestUsd, { compact: true }) : ' · 매수 기록을 이으면 수익률이 보여요'), usd: num(D.unkhUsd), go: '연결하기', a: 'goPend', k: 'unkh' });
    const others = D.pendVis.filter(p => p._cat !== 'unkh');
    if (others.length) {
      const oc = {}; others.forEach(p => { oc[p._cat] = (oc[p._cat] || 0) + 1; });
      const cs = PCAT_ORDER.filter(c => oc[c]);
      const brk = cs.slice(0, 2).map(c => PCATS[c].label + ' ' + oc[c] + '건').join(' · ');
      const uF = sum(arr(D.merged).filter(c => !c._lp), c => num(pAgg(c).allU));
      it.push({ tip: '건 = 미매칭 목록의 행 — 원가 미확인 매도는 코인별 1행' + (oc.unv && uF ? '(체결로는 ' + nf('ko-KR').format(uF) + '회 — 매매일지 머리 숫자)' : '') + ' · 보유는 코인 수(종)', ico: 'w', col: 'var(--warn)', i: IC.info, t: '미매칭 기록', n: others.length + '건', d: brk + ' 포함' + (oc.unv ? ' · 실현손익에서 빠져 있어요' : '') + (D.unkhSymN ? ' · 미매칭 탭 ' + D.pendN + '개 = 기록 ' + others.length + '건 + 보유 ' + D.unkhSymN + '종' : ''), usd: pendVisUsd, go: '맞추기', a: 'go', k: 'unmatched' });
    }
    return it;
  }
  function todoProgress(it) {
    const n = sum(it, x => parseInt(String(x.n).replace(/[^\d]/g, ''), 10) || 0), td = todayISO();
    let H = {};
    try { H = JSON.parse(LS.get('tj_v2_todo_hist') || '{}') || {}; } catch (e) { H = {}; }
    if (!H || typeof H !== 'object' || Array.isArray(H)) H = {};
    let dirty = false;
    Object.keys(H).forEach(k => { const v = H[k], c = Array.isArray(v) ? v[0] : v;
      if (!isISO(k) || typeof c !== 'number' || !isFinite(c) || c < 0) { delete H[k]; dirty = true; } else if (v !== c) { H[k] = c; dirty = true; } });
    if (H[td] == null) { H[td] = n; dirty = true; const ks = Object.keys(H).sort(); ks.slice(0, Math.max(0, ks.length - 21)).forEach(k => delete H[k]); }
    if (dirty) LS.set('tj_v2_todo_hist', JSON.stringify(H));
    const wk = isoAdd(td, -7), base = Object.keys(H).sort().find(k => k >= wk && k < td);
    if (!base) return '';
    const n0 = H[base], dn = n0 - n;
    if (dn <= 0) return '';
    return '<div class="tprog pvx"><span class="tpb" aria-hidden="true"><i style="width:' + Math.max(4, Math.min(100, n0 ? dn / n0 * 100 : 0)).toFixed(0) + '%"></i></span>'
      + '<span>이번 주 <b class="num">' + dn + '</b>개 정리 · 남은 <b class="num">' + n + '</b>개</span></div>';
  }
  function todoNext() {
    const D = S.D, ym = ymShift(0);
    if (!D.dayActs || !D.dmOk) return '';
    const days = Object.keys(D.dayActs).filter(k => k.slice(0, 7) === ym && num(D.dayActs[k].s) > 0).sort();
    const memo = new Set(Object.keys(D.dayMemos || {}).map(k => k.slice(0, 10)));
    const miss = days.filter(k => !memo.has(k));
    if (!miss.length) return '';
    return '<button class="tnext" data-a="goDay" data-v="' + esc(miss[miss.length - 1].slice(5)) + '"><span>이번 달 매매한 <b class="num">' + days.length + '</b>일 중 <b class="num">' + miss.length + '</b>일에 매매 근거 메모가 없어요</span><span class="sp"></span><span class="go">최근 날에 남기기 ›</span></button>';
  }
  function preData() { const D = S.D; return !!D && ((!arr(D.wallets).length && !D.exN) || /대기/.test(String(D.lastScan || '수집 대기'))); }
  function exLinked() { try { const ex = window.__tjSetup && window.__tjSetup.U && window.__tjSetup.U.st && window.__tjSetup.U.st.exchanges; if (ex && typeof ex === 'object') return Object.keys(ex).filter(k => ex[k] && ex[k].set).length; } catch (e) {  } return num(S.D && S.D.exN); }
  function todoHTML() {
    const D = S.D, it = attnItems().sort((a, b) => num(b.usd) - num(a.usd));
    const hid = D.pendHid.length, pg = D.priceGuard.length, up = D.upN;
    const big = it.filter(x => x.usd > 0).sort((a, b) => b.usd - a.usd)[0];
    const mob = S.mobile;
    const head = mob
      ? '<div class="th m"><h2 class="pvx">' + (it.length ? '정리할 것 <span class="num">' + it.length + '</span>가지' : '정리할 것 없음') + '</h2><span class="cap pvx">' + esc(it.map(x => x.t.replace(/ (확인|보유|기록)$/, '').replace('원가 미확인', '원가') + ' ' + x.n).join(' · ')) + '</span></div>'
      : '<div class="th"><h2>정리할 것' + (it.length ? ' <span class="cnt num pvx">' + it.length + '</span>' : '') + '</h2><button class="link" data-a="go" data-v="unmatched">모두 보기</button></div>';
    const rows = it.length ? '<div class="tdos">' + it.map(x => '<button class="tdo" data-a="' + x.a + '"' + (x.k ? ' data-v="' + x.k + '"' : '') + (x.tip ? ' title="' + esc(x.tip) + '"' : '') + '>'
      + '<span class="tbar" style="background:' + x.col + '" aria-hidden="true"></span>'
      + '<span class="tx"><b>' + x.t + '</b><span class="d">' + nbDot(x.d) + '</span></span>'
      + '<span class="tr"><span class="cnt num">' + x.n + '</span>' + (x.usd > 0 ? '<span class="amt num">' + m(x.usd, { compact: true }) + '</span>' : '') + '</span></button>').join('') + '</div>'
      : preData() ? '<div class="ok0"><span class="pill g sm">수집 전</span>아직 수집 전이에요 — 지갑·거래소를 연결하고 첫 수집이 끝나면 정리할 것을 여기 모아 보여줘요</div>'
      : '<div class="ok0"><span class="pill ok sm">' + IC.check.replace('<svg', '<svg width="12" height="12"') + ' 깨끗</span>미매칭·외부 전송·원가 미확인이 모두 정리됐어요</div>' + todoNext();
    const capL = it.length ? '<div class="cap tcap">금액이 걸린 것만 · 처리하면 손익·평균 매수가에 바로 반영' + (big && it.length > 1 ? ' · 가장 큰 것 ' + esc(big.t) + ' <span class="num">' + m(big.usd, { compact: true }) + '</span>' : '') + '</div>' : '';
    const ex = (pg || up || hid) ? '<div class="exrow">' + IC.eyeoff + (pg || up ? '<b>평가 제외</b>' + (pg ? '<button data-a="guardInfo">가격 이상 ' + pg + '종</button>' : '') + (pg && up ? '<span>·</span>' : '') + (up ? '<button class="pvx" data-a="unpricedInfo" title="시세를 못 찾은 코인 전체(소액·스캠 포함)예요 — 설정 › 상태의 \'시세 없는 실보유\'는 그중 원가·참고가가 큰 실보유만 세요">시세 없음 ' + up + '개</button>' : '') + '<span>— 총자산·손익 합계에 넣지 않았어요</span>' : '')
      + '<span class="sp"></span>' + (hid ? '<button class="go" data-a="goHidden" title="미매칭 › 자동으로 숨긴 항목(소액·스캠·표시용 보정)">자동으로 숨긴 항목 ' + hid + '건 · 보기 ›</button>' : '') + '</div>' : '';
    return '<section class="card todo' + (mob && it.length ? ' hasw' : '') + '" aria-label="정리할 것">' + head + (it.length ? todoProgress(it) : '') + rows + capL + ex + '</section>';
  }
  function allocHTML() {
    const D = S.D, T = D.total || 1;
    const cls4 = [['스테이블', D.stableTotal, 'var(--c1)'], ['원화 예수금', D.fiatTotal, 'var(--c2)'], ['코인', D.coinTotal, 'var(--c3)'], ['LP (미청구 포함)', D.lpTotal, 'var(--c4)']];
    const bar = cls4.filter(c => c[1] > 0).map(c => '<i style="flex:' + (c[1] / T * 100).toFixed(3) + ';background:' + c[2] + '" title="' + c[0] + '"></i>').join('');
    const leg = cls4.filter(c => c[1] > 0 || c[0].indexOf('LP') !== 0).map(c => '<div><span class="ll"><span class="sw" style="background:' + c[2] + '"></span>' + c[0] + '</span><b class="num">' + m(c[1], { compact: true }) + '</b><span class="mut num">' + (c[1] / T * 100).toFixed(1) + '%</span></div>').join('');
    return '<div class="card alloc"><div class="row" style="flex-wrap:wrap;gap:6px 12px"><h2 class="h2">자산 구성</h2><div class="sp"></div><div class="cap num">현금성 <span class="num">' + (D.cashTotal / T * 100).toFixed(1) + '%</span> · 코인은 온체인 ' + mN(D.coinDex, { compact: true }) + ' · 거래소 ' + mN(D.coinCex, { compact: true }) + (D.debts.length ? ' · ' + esc(D.debtLbl) + ' ' + mN(D.debtUsd, { sign: true, compact: true }) + ' 차감됨' : '') + '</div></div>'
      + '<div class="bar">' + bar + '</div><div class="leg">' + leg + '</div></div>';
  }
  function holdRows() {
    const D = S.D, mode = S.hold.mode;
    let rows = D.groups.map(g => {
      const v = mode === 'wallet' ? g.wValue : mode === 'cex' ? g.xValue : g.value;
      return { g, value: v, frac: g.value > 0 ? v / g.value : (mode === 'all' ? 1 : 0) };
    }).filter(r => mode === 'all' ? (r.g.qty > 0) : r.value > 0);
    rows = rows.filter(r => r.value > 0);
    const hidden = rows.filter(r => !dustOk(r.value));
    rows = rows.filter(r => dustOk(r.value));
    const k = S.hold.sort, dir = S.hold.dir;
    rows.sort((a, b) => {
      const va = k === 'roi' ? a.g.roi : k === 'pnl' ? (a.g.cost > 0 ? a.g.pnl * a.frac : null) : a.value;
      const vb = k === 'roi' ? b.g.roi : k === 'pnl' ? (b.g.cost > 0 ? b.g.pnl * b.frac : null) : b.value;
      if (va == null && vb == null) return b.value - a.value;
      if (va == null) return 1; if (vb == null) return -1;
      return (va - vb) * dir || b.value - a.value;
    });
    const at = new Map(rows.map(r => [r.g.key, r]));
    const subs = rows.filter(r => r.g.rabby && String(r.g.key).indexOf('#rb:') === 0 && at.has(String(r.g.key).slice(4)));
    if (subs.length) {
      rows = rows.filter(r => subs.indexOf(r) < 0);
      subs.forEach(r => { const i = rows.indexOf(at.get(String(r.g.key).slice(4))); if (i < 0) { rows.push(r); return; } let j = i + 1; while (j < rows.length && rows[j].sub) j++; rows.splice(j, 0, Object.assign(r, { sub: true })); });
    }
    const tc = new Map(); rows.forEach(r => { if (r.g.twin) { const s0 = String(r.g.sym).toUpperCase(); tc.set(s0, (tc.get(s0) || 0) + 1); } });
    twinVis = new Set(rows.filter(r => r.g.twin && tc.get(String(r.g.sym).toUpperCase()) > 1).map(r => r.g.key));
    return { rows, hidden };
  }
  function planOfGroup(g) {
    for (const k of g.keys) if (S.D.plans[k]) return { key: k, plan: S.D.plans[k], price: S.D.priceOf[k] };
    const mp = S.D.merged.find(p => gMatch(g, p.sym, p.key) && S.D.plans[p.key]);
    return mp ? { key: mp.key, plan: S.D.plans[mp.key], price: mp._price } : null;
  }
  const gIcon = (g, sz) => icon(g.sym, sz, { ck: g.logo.ck, ca: g.logo.ca, chain: g.logo.chain });
  const gRb = g => !!(g.rabby && String(g.key).indexOf('#rb:') === 0);
  let twinVis = new Set();
  const twinChip = g => g.twin && twinVis.has(g.key) ? ' <span class="kchip" title="' + esc('같은 이름(' + g.sym + ')이지만 시세가 1.5배 넘게 달라 다른 코인으로 따로 보여요 — 이 줄 시세 ' + pxC(num((g.insts.find(i => i.price > 0) || {}).price))) + '">이름만 같음</span>' : '';
  const gName = g => esc(g.sym) + (gRb(g) && g.rbKind ? '<span class="rbnm"> · ' + esc(g.rbKind) + '</span>' : '') + twinChip(g);
  const gTip = g => g.sym + (gRb(g) ? (g.rbKind ? ' · ' + g.rbKind : '') + ' (Rabby 기준)' : '');
  const gSub = (g, t) => esc(t) + (gRb(g) ? ' · Rabby 기준' : '');
  function roiPct(g) {
    if (g.unpriced && g.value <= 0) return '<span class="pill w sm">시세 없음</span>';
    if (g.roi == null && g.rabby) return '<span class="kchip" title="봇 원가·손익 추적 밖 — Rabby(DeBank 데이터) 수량·USD 로 평가만 해요">원가 추적 밖</span>';
    if (g.roi == null) return '<span class="kchip" title="원가 기록이 없어 평가손익·수익률을 계산하지 못해요 — 펼쳐서 원가 지정">원가 미확인</span>';
    const covR = (1 - g.unkPct) * 100, cov = Math.max(0, Math.min(100, Math.round(covR))), covS = cov < 1 ? '1% 미만' : cov + '%', weak = g.unkPct >= 0.8, approx = !weak && g.unkPct >= 0.2;
    if (covR < 10) { const sk = stakeUnk(g); return '<span class="kchip" title="보유 평가의 ' + covS + '만 원가 확인 — 확인된 수량만의 수익률 ' + esc(pctS(g.roi, 1)) + '(전체 성과 아님)' + (sk ? esc(' · 스테이킹 ' + q(sk.qty) + ' ' + g.sym + ' 원가 미확인(수집 시작 전 위임) — 펼쳐서 원가 지정') : '') + '">' + (sk ? '스테이킹 원가 미확인' : '원가 대부분 미확인') + '</span>' + fsKchip(g.fsc); }
    const tip = g.unkPct >= 0.005 ? ' title="보유 평가의 ' + covS + '만 원가 확인 — 확인된 수량만의 수익률"' : '';
    return (g.unkPct >= 0.005 ? '<span class="kchip"' + tip + '>원가 확인 ' + covS + '</span>' : '') + fsKchip(g.fsc) + '<span class="pct num ' + (weak ? 'weak' : cls(g.roi)) + (approx ? ' approx' : '') + '"' + tip + '>' + pctS(g.roi, 1) + '</span>';
  }
  const fsKchip = (usd, what) => num(usd) >= 0.005 ? '<span class="kchip pvx" data-pvt="1" title="' + esc((what || '원가') + ' 중 ' + m(num(usd)) + '는 최초 인식 시가(원가를 모르던 수량을 그 수량이 장부에 처음 생긴 날 시가로 잡은 값)예요 · 설정 › 원가 계산에서 끌 수 있어요') + '">추정</span>' : '';
  const holdKeyOk = g => !g.rabby && g.key === String(g.sym).toUpperCase();
  const todayOf = g => { const T = S.D.todayBy; if (!T || !holdKeyOk(g)) return null; const e = T[g.key]; if (!Array.isArray(e)) return null; const pct = e[0] == null ? null : num(e[0]), usd = num(e[1]); return pct == null && !usd ? null : { pct, usd }; };
  const sparkOf = g => { const P = S.D.spark7; if (!P || !holdKeyOk(g)) return null; const a = P[g.key]; return Array.isArray(a) && a.filter(x => x != null && isFinite(x) && x > 0).length >= 2 ? a : null; };
  const TODAY_TIP = '오늘 변동 = 오늘 가격 변동률(어제 마감 대비) · 그 코인이 오늘 총자산에 보탠 금액(전일 보유 × 가격 변화 — 대시보드 \'오늘 무엇이 움직였나\'와 같은 수)';
  const TODAY_NONE = '오늘 변동 없음 — 전일 마감 보유가 없거나(오늘 처음 산 코인) 아직 분해 기록이 없어요';
  const todayPct = g => { const t = todayOf(g); return t && t.pct != null ? '<span class="tp ' + cls(t.pct) + '">' + pctS(t.pct, 1) + '</span>' : '<span class="tp mut">—</span>'; };
  function todayCell(g) {
    const t = todayOf(g);
    if (!t) return '<span class="tdc num mut" title="' + esc(TODAY_NONE) + '">—</span>';
    return '<span class="tdc num" title="' + esc(TODAY_TIP + ' — ' + (t.pct != null ? pctS(t.pct, 2) + ' · ' : '') + m(t.usd, { sign: true })) + '">' + (t.pct != null ? '<span class="tp ' + cls(t.pct) + '">' + pctS(t.pct, 1) + '</span><span class="td">·</span>' : '')
      + '<span class="ta ' + cls(t.usd) + '">' + m(t.usd, { sign: true, compact: true }) + '</span></span>';
  }
  function sparkSVG(a, w, h) {
    if (!a) return '';
    const pts = a.map((v, i) => [i, v != null && isFinite(v) && v > 0 ? +v : null]).filter(p => p[1] != null);
    if (pts.length < 2) return '';
    const vs = pts.map(p => p[1]), lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs), n = Math.max(1, a.length - 1), pad = 2.5;
    const X = i => (pad + i / n * (w - pad * 2)).toFixed(1), Y = v => (hi > lo ? pad + (hi - v) / (hi - lo) * (h - pad * 2) : h / 2).toFixed(1);
    const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]) + ' ' + Y(p[1])).join(''), first = pts[0], last = pts[pts.length - 1];
    const k = last[1] > first[1] ? 'up' : last[1] < first[1] ? 'down' : 'flat';
    const area = d + 'L' + X(last[0]) + ' ' + (h - 0.5) + 'L' + X(first[0]) + ' ' + (h - 0.5) + 'Z';
    return '<svg class="spk ' + k + '" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="7일 추이 ' + (k === 'up' ? '상승' : k === 'down' ? '하락' : '보합') + '"><path class="a" d="' + area + '"/><path class="l" d="' + d + '"/><circle cx="' + X(last[0]) + '" cy="' + Y(last[1]) + '" r="2"/></svg>';
  }
  const sparkCell = (g, w, h) => sparkSVG(sparkOf(g), w, h) || '<span class="mut" title="7일 추이 없음 — 지난날 마감가가 아직 없어요">—</span>';
  const xChev = open => IC.chev.replace('<svg', '<svg class="xch' + (open ? ' o' : '') + '"');
  function covCell(g) {
    if (g.unpriced && g.value <= 0) return '';
    if (g.roi == null) return g.rabby ? '<span class="cvt mut">추적 밖</span>' : '<div class="cov2"><b><i style="width:0"></i></b><span>없음</span></div>';
    const covR = (1 - g.unkPct) * 100, cov = Math.max(0, Math.min(100, Math.round(covR))), sk = covR < 10 ? stakeUnk(g) : null;
    const t = g.unkPct < 0.005 ? '100%' : sk ? '스테이킹 원가 미확인' : cov < 1 ? '1% 미만' : cov + '%';
    return '<div class="cov2" title="보유 평가 중 원가가 확인된 몫 ' + (cov < 1 && g.unkPct >= 0.005 ? '1% 미만' : cov + '%') + '"><b><i style="width:' + Math.max(g.unkPct < 0.005 ? 100 : cov, 2) + '%"></i></b><span>' + t + '</span></div>';
  }
  const holdPgHit = k => r => !!r && !!r.g && r.g.key === k;
  function holdingsHTML() {
    const D = S.D;
    const { rows, hidden } = holdRows();
    const nCoin = rows.filter(r => !r.sub).length;
    const pgH = uiPgSlice('hold', rows), shown = pgH.rows;
    const seg = '<div class="seg" role="group" aria-label="보관 구분">' + [['all', '전체'], ['wallet', '지갑'], ['cex', '거래소']].map(x => '<button data-a="holdMode" data-v="' + x[0] + '" class="' + (S.hold.mode === x[0] ? 'on' : '') + '" aria-pressed="' + (S.hold.mode === x[0]) + '">' + x[1] + '</button>').join('') + '</div>';
    const dustLink = S.dust > 0 && (hidden.length || S.hold.showDust) ? '<button class="link" data-a="toggleDust" style="font-weight:600;color:var(--muted)">' + (S.hold.showDust ? '소액 숨기기' : '소액 ' + hidden.length + '종 숨김 · 보기') + '</button>' : '';
    const dense = S.hold.dense && !S.mobile;
    const dseg = S.mobile ? '' : '<div class="seg dseg" role="group" aria-label="행 밀도">' + [['0', '기본'], ['1', '촘촘히']].map(x => '<button data-a="holdDense" data-v="' + x[0] + '" class="' + ((dense ? '1' : '0') === x[0] ? 'on' : '') + '" aria-pressed="' + ((dense ? '1' : '0') === x[0]) + '">' + (x[0] === '1' ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>' : '') + x[1] + '</button>').join('') + '</div>';
    const head = '<div class="tblhead"><h2 class="h2">보유 코인</h2><span class="cap num">' + nCoin + '종 · ' + ({ value: '평가금액', roi: '수익률', pnl: '평가손익' })[S.hold.sort] + ' 순</span>' + dustLink + '<div class="sp"></div>' + seg + dseg + '</div>';
    if (!rows.length) {
      return '<div class="card">' + head + '<div class="empty"><div class="eic">' + IC.coin + '</div><b>' + (D.groups.length ? '표시할 코인이 없어요' : '보유 코인이 없어요') + '</b>'
        + (hidden.length ? '소액 기준($' + S.dust + ') 미만 ' + hidden.length + '종이 숨겨져 있어요. <button class="link" data-a="toggleDust">모두 보기</button>' : '지갑 스캔·거래소 동기화 후 여기에 나타나요.') + '</div>' + zeroFoldHTML() + debtFootHTML() + '</div>';
    }
    let body;
    if (S.mobile) {
      body = '<div class="m-list">' + shown.map(r => {
        const g = r.g, open = S.hold.open.has(g.key);
        const xchips = trChip(g.tr, g.locSummary) + staleChip(g) + (r.sub ? rbChip(g).replace('>Rabby 기준 · ', '>Rabby · ') : rbChip(g));
        return '<div class="it' + (r.sub ? ' rbsub' : '') + '" role="button" tabindex="0" data-a="holdTog" data-k="' + esc(g.key) + '" data-anc="coin:' + esc(g.key) + '" aria-expanded="' + open + '">' + gIcon(g)
          + '<div class="mb"><div class="mb1"><div class="sym ell" title="' + esc(gTip(g)) + '">' + gName(g) + impChip(g) + '</div><span class="ch ell">' + gSub(g, g.chainLabel) + '</span>'
          + '<div class="val num" data-fl="h:' + esc(g.key) + '" data-v="' + (S.hide || S.rand ? 0 : r.value.toFixed(2)) + '" title="' + esc(m(r.value)) + '">' + m(r.value, { compact: true }) + '</div></div>'
          + '<div class="mb2"><div class="l2 num">' + roiPct(g) + (r.sub ? '' : '<span class="td">·</span><span class="tdl" title="' + esc(todayOf(g) ? TODAY_TIP : TODAY_NONE) + '">오늘 ' + todayPct(g) + '</span>') + '</div>' + (xchips ? '<div class="mbx ell">' + xchips + '</div>' : '') + '</div></div>'
          + '<div class="spm">' + sparkSVG(sparkOf(g), 56, 20) + '</div></div>'
          + (open ? clps('h:' + g.key, holdDetail(r)) : '');
      }).join('') + '</div>';
    } else if (dense) {
      body = holdDenseHTML(shown);
    } else {
      body = '<table class="ht hx"><colgroup><col style="width:27%"><col style="width:17%"><col style="width:20%"><col style="width:20%"><col style="width:16%"></colgroup><thead class="stk"><tr><th scope="col">자산</th>' + holdTh('value', '평가금액')
        + holdThDual() + '<th scope="col" title="' + esc(TODAY_TIP) + '">오늘 변동</th><th scope="col" title="지난 6일 그날 마감가 + 오늘 시세 — 7일 전보다 올랐으면 빨강, 내렸으면 파랑">7일 추이</th></tr></thead><tbody>'
        + shown.map(r => {
          const g = r.g, open = S.hold.open.has(g.key);
          const pnl = g.cost > 0 ? g.pnl * r.frac : null;
          return '<tr class="clk' + (open ? ' open' : '') + (r.sub ? ' rbsub' : '') + '" data-a="holdTog" data-k="' + esc(g.key) + '" data-anc="coin:' + esc(g.key) + '" role="button" tabindex="0" aria-expanded="' + open + '">'
            + '<td><div class="asset">' + gIcon(g) + '<div class="ell"><div class="sym ell" title="' + esc(gTip(g)) + '">' + gName(g) + impChip(g) + '</div><div class="sub ell">' + gSub(g, g.chainLabel) + '</div></div></div></td>'
            + '<td><div class="val num" data-fl="h:' + esc(g.key) + '" data-v="' + (S.hide || S.rand ? 0 : r.value.toFixed(2)) + '" title="' + esc(m(r.value)) + '">' + m(r.value, { compact: true }) + '</div><div class="sub num">' + q(r.frac < 1 ? g.qty * r.frac : g.qty) + ' ' + esc(g.sym.length > 8 ? '' : g.sym) + staleChip(g) + rbChip(g) + '</div></td>'
            + '<td>' + holdPnl(g, pnl, false) + '<div class="rpc">' + roiPct(g) + '</div></td>'
            + '<td>' + todayCell(g) + '</td>'
            + '<td><div class="spc">' + sparkCell(g, 80, 24) + xChev(open) + '</div></td></tr>'
            + (open ? '<tr class="xrow"><td colspan="5">' + clps('h:' + g.key, holdDetail(r)) + '</td></tr>' : '');
        }).join('') + '</tbody></table>';
    }
    const zf = zeroFoldHTML();
    const foot = pgH.last > 0 ? '<div class="foot hpg">' + uiPgBar('hold', rows.length, { unit: rows.length > nCoin ? '줄' : '종' }) + '</div>' : '';
    return '<div class="card">' + (pgH.last > 0 ? '<div class="upga" data-pga="hold"></div>' : '') + head + body + foot + zf + debtFootHTML() + '</div>';
  }
  function debtFootHTML() {
    const D = S.D, neg = (D.groups || []).filter(g => num(g.qty) < 0 && num(g.value) <= -0.005);
    if (!neg.length || S.hold.mode !== 'all') return '';
    return '<div class="foot zfold"><span><span class="pvx">빌린 몫이 잔고를 넘은 코인 <b class="num">' + neg.length + '</b>종</span> · <b class="num">' + m(sum(neg, g => num(g.value)), { compact: true }) + '</b> <span class="mut pvx">· '
      + esc(neg.slice(0, 3).map(g => g.sym).join(' · ') + (neg.length > 3 ? ' 외' : '')) + ' — 총자산에서 차감 · 빌린 돈은 레버리지·대출 칸</span></span></div>';
  }
  function zeroFoldHTML() {
    const D = S.D, z = D.zeroInst || [];
    if (!z.length || S.hold.mode !== 'all') return '';
    const nG = z.filter(x => x.guard).length, nV = z.filter(x => x.unv && !x.guard).length, nU = z.length - nG - nV, open = S.hold.showZero;
    const why = [nG ? '가격 이상 ' + nG : '', nU ? '시세 없음 ' + nU : '', nV ? '확인 필요 ' + nV : ''].filter(Boolean).join(' · ');
    const it = x => '<div class="zi" data-anc="zcoin:' + esc(String(x.sym || '').toUpperCase()) + '"><b class="ell">' + esc(x.sym) + '</b><span class="ell mut">' + (x.chain ? esc(x.chain) : x.where.length ? x.where.slice(0, 2).map(locH).join(' · ') : '거래소') + '</span><span class="num">' + q(x.qty) + '</span>'
      + (x.guard ? '<span class="pill w sm">가격 이상</span>'
        : x.unv ? '<button class="pill w sm" data-a="unvTok" data-k="' + esc(x.key) + '" title="' + esc(x.unv) + ' 이름이지만 정품 목록에 없는 컨트랙트예요 — 눌러서 확인">확인 필요</button>'
        : x.genU ? '<button class="pill a sm" data-a="genTok" data-k="' + esc(x.key) + '" title="직접 정품으로 등록한 컨트랙트 — 눌러서 등록 풀기">직접 등록</button>'
        : x.cost >= 1 ? '<span class="pill g sm" title="원가 ' + esc(m(x.cost)) + ' — 시세가 없어 평가 0">원가 있음</span>' : '<span></span>') + '</div>';
    return '<div class="foot zfold"><span class="pvx"><span class="nowrap">값 없는 토큰 <b class="num">' + z.length + '</b>개</span> <span class="mut"><span class="nowrap">· ' + why + '</span> <span class="nowrap">— 평가 0 ·</span> <span class="nowrap">총자산 밖</span></span></span>'
      + '<button class="link" data-a="holdZero" aria-expanded="' + open + '">' + (open ? '접기' : '보기') + (open ? '' : IC.right) + '</button></div>'
      + (open ? (() => { const pz = uiPgSlice('zero', z); return (pz.last > 0 ? '<div class="upga" data-pga="zero"></div>' : '') + '<div class="zlist">' + pz.rows.map(it).join('') + '</div>' + uiPgBar('zero', z.length, { unit: '개', cls: 'zpg' }); })() : '');
  }
  const holdTh = (k, label, x) => '<th scope="col" class="sort' + (S.hold.sort === k ? ' on' : '') + (x ? ' ' + x : '') + '" aria-sort="' + (S.hold.sort === k ? (S.hold.dir < 0 ? 'descending' : 'ascending') : 'none') + '"><button class="thb" data-a="holdSort" data-v="' + k + '" aria-label="' + label + ' 순 정렬' + (S.hold.sort === k ? (S.hold.dir < 0 ? ' (지금 큰 순 — 누르면 작은 순)' : ' (지금 작은 순 — 누르면 큰 순)') : '') + '">' + label + (S.hold.sort === k ? (S.hold.dir < 0 ? ' ↓' : ' ↑') : '') + '</button></th>';
  const holdThDual = () => '<th scope="col" class="sort dual' + (S.hold.sort === 'pnl' || S.hold.sort === 'roi' ? ' on' : '') + '" aria-sort="' + (S.hold.sort === 'pnl' || S.hold.sort === 'roi' ? (S.hold.dir < 0 ? 'descending' : 'ascending') : 'none') + '">' + ['pnl', 'roi'].map(k0 => '<button class="thb' + (S.hold.sort === k0 ? ' on' : '') + '" data-a="holdSort" data-v="' + k0 + '" aria-label="' + (k0 === 'pnl' ? '평가손익' : '수익률') + ' 순 정렬' + (S.hold.sort === k0 ? (S.hold.dir < 0 ? ' (지금 큰 순 — 누르면 작은 순)' : ' (지금 작은 순 — 누르면 큰 순)') : '') + '">' + (k0 === 'pnl' ? '평가손익' : '%') + (S.hold.sort === k0 ? (S.hold.dir < 0 ? ' ↓' : ' ↑') : '') + '</button>').join('<span class="thd" aria-hidden="true">·</span>') + '</th>';
  const holdPnl = (g, pnl, dense) => pnl == null ? '<div class="pnl mut">—</div>' : (g.unkPct >= 0.8 ? '<div class="pnl num mut" title="보유의 ' + Math.round(g.unkPct * 100) + '%가 원가 미확인 — 확인된 수량만의 평가손익">' + m(pnl, { sign: true, compact: true }) + '</div>' : '<div class="pnl num ' + cls(pnl) + '" title="' + esc(m(pnl, { sign: true })) + '">' + m(pnl, { sign: true, compact: true }) + '</div>');
  function holdDenseHTML(shown) {
    return '<table class="ht dense"><colgroup><col style="width:28%"><col style="width:17%"><col style="width:21%"><col style="width:19%"><col style="width:15%"></colgroup><thead class="stk"><tr><th scope="col">자산</th>' + holdTh('value', '평가금액') + holdThDual()
      + '<th scope="col" title="' + esc(TODAY_TIP) + '">오늘 변동</th><th scope="col" title="지난 6일 그날 마감가 + 오늘 시세 — 7일 전보다 올랐으면 빨강, 내렸으면 파랑">7일 추이</th></tr></thead><tbody>'
      + shown.map(r => {
        const g = r.g, open = S.hold.open.has(g.key);
        const pnl = g.cost > 0 ? g.pnl * r.frac : null;
        const low = g.roi != null && (1 - g.unkPct) * 100 < 10;
        return '<tr class="clk' + (open ? ' open' : '') + (low ? ' lowcov' : '') + (r.sub ? ' rbsub' : '') + '" data-a="holdTog" data-k="' + esc(g.key) + '" data-anc="coin:' + esc(g.key) + '" role="button" tabindex="0" aria-expanded="' + open + '">'
          + '<td><div class="asset">' + gIcon(g, 'xs') + '<b class="sym" title="' + esc(gTip(g)) + '">' + gName(g) + '</b>' + impChip(g) + '<span class="ch ell">' + esc(g.chainLabel) + '</span></div></td>'
          + '<td><div class="v2"><span class="val num" data-fl="h:' + esc(g.key) + '" data-v="' + (S.hide || S.rand ? 0 : r.value.toFixed(2)) + '" title="' + esc(m(r.value)) + '">' + m(r.value, { compact: true }) + '</span><span class="sub num qn">' + q(r.frac < 1 ? g.qty * r.frac : g.qty) + ' ' + esc(g.sym.length > 8 ? '' : g.sym) + staleChip(g) + rbChip(g) + '</span></div></td>'
          + '<td>' + holdPnl(g, pnl, true) + '<div class="rpc">' + roiPct(g) + '</div></td>'
          + '<td>' + todayCell(g) + '</td>'
          + '<td><div class="spc">' + sparkCell(g, 64, 20) + xChev(open) + '</div></td></tr>'
          + (open ? '<tr class="xrow"><td colspan="5">' + clps('h:' + g.key, holdDetail(r)) + '</td></tr>' : '');
      }).join('') + '</tbody></table>';
  }
  function stakeUnk(g) {
    if (!(g.unkQty > 0)) return null;
    let qty = 0, rw = 0;
    g.locList.forEach(L => { if (!/· 스테이킹$/.test(String(L.w))) return; L.subs.forEach(s0 => { qty += num(s0.qty); const mm = /누적 보상 ([\d,.]+)/.exec(String(s0.sub || '')); if (mm) rw += num(mm[1].replace(/,/g, '')); }); });
    const pr = Math.min(Math.max(0, qty - rw), g.unkQty);
    return pr > 0 ? { qty: pr, pct: g.qty > 0 ? pr / g.qty * 100 : 0 } : null;
  }
  const stakeNote = g => { const k = stakeUnk(g); return k ? '<div class="fbnote stkn">스테이킹 ' + q(k.qty) + ' ' + esc(g.sym) + ' 원가 미확인(수집 시작 전 위임) — 원가를 지정하면 수익률을 계산해요'
    + ' <button class="link" data-a="goPend" data-v="unkh" data-q="' + esc(g.sym) + '">원가 지정' + IC.right + '</button></div>' : ''; };
  function holdDetail(r) {
    const g = r.g, D = S.D;
    const locRows = [];
    g.locList.forEach(L => L.subs.forEach((s, i) => {
      if (S.hold.mode === 'wallet' && !L.wallet) return;
      if (S.hold.mode === 'cex' && L.wallet) return;
      const sub = (s.ch && String(s.sub).indexOf(s.ch) === 0) ? s.sub : [s.ch, s.sub].filter(Boolean).join(' · ');
      locRows.push(S.mobile ? '<div class="kv"><span class="ell">' + (i === 0 ? '<b style="color:var(--text)">' + locH(L.w) + '</b>' : '') + trChip(s.tr, L.w + ' ' + sub) + '<div class="sub ell' + (s.tr ? ' trs' : '') + '">' + esc(sub) + '</div></span><b class="num">' + m(s.value) + '<div class="sub">' + q(s.qty) + '</div></b></div>'
        : '<tr><td>' + (i === 0 ? '<b>' + locH(L.w) + '</b>' : '') + trChip(s.tr, L.w + ' ' + sub) + '<div class="sub ell' + (s.tr ? ' trs' : '') + '" style="max-width:260px">' + esc(sub) + '</div></td><td class="num">' + q(s.qty) + '</td><td class="num">' + m(s.value) + '</td></tr>');
    }));
    const inst = g.insts.filter(i => !i.zero).sort((a, b) => b.value - a.value).slice(0, 12).map(i => {
      const note = (!i.hasCost ? (i.price > 0 ? '<span class="pill w sm">원가 미확인</span>' : '<span class="pill w sm">시세 없음</span>')
        : (i.unkQty > 0 ? '<span class="pill w sm">원가 미확인 ' + q(i.unkQty) + '</span>' : (i.fbCost > 0 ? '<span class="pill a sm">평균가 대체</span>' : ''))
      ) + (i.genU && i.ca ? ' <button class="pill a sm" data-a="genTok" data-k="' + esc(i.key) + '" title="직접 정품으로 등록한 컨트랙트 — 눌러서 등록 풀기">직접 등록</button>' : '');
      if (S.mobile) return '<div class="kv"><span class="ell"><b style="color:var(--text)">' + esc(i.chain || '거래소') + '</b> ' + note + '<div class="sub">' + q(i.qty) + ' · 평단 ' + pxC(i.avg) + '</div><div class="sub">현재 ' + pxC(i.price) + (pxSrcTxt(i) ? ' · <span class="nowrap">' + esc(pxSrcTxt(i)) + '</span>' : '') + '</div></span><b class="num">' + (i.hasCost ? m(i.cost) : '—') + '<div class="sub num ' + cls(i.pnl) + '" style="font-weight:650">' + (i.hasCost ? m(i.pnl, { sign: true }) : '') + '</div></b></div>';
      return '<tr><td><b>' + esc(i.chain || '거래소') + '</b><div class="sub">' + q(i.qty) + ' · 평단 ' + pxC(i.avg) + ' · 현재 ' + pxC(i.price) + (pxSrcTxt(i) ? ' · <span class="nowrap">' + esc(pxSrcTxt(i)) + '</span>' : '') + '</div></td><td class="num">' + (i.hasCost ? m(i.cost) : '<span class="mut">—</span>') + '<div>' + note + '</div></td><td class="num ' + cls(i.pnl) + '">' + (i.hasCost ? m(i.pnl, { sign: true }) : '<span class="mut">—</span>') + '</td></tr>';
    }).join('');
    const pl = planOfGroup(g);
    const plan = pl ? (() => {
      const p = pl.plan, price = pl.price, span = p.target - p.stop;
      const pos = span > 0 && price > 0 ? Math.max(2, Math.min(98, (price - p.stop) / span * 100)) : 50;
      return '<div class="blk" style="margin-top:12px"><div class="ttl">목표 · 손절 <span class="pill ' + (p.src === 'DEX' ? 'a' : 'ok') + ' sm">' + esc(p.src || 'CEX') + ' 추적</span></div>'
        + '<div class="kv"><span>목표가</span><b class="num">' + plPx(p.target) + ' <span class="' + clsP((p.target - price) / price * 100) + '">' + pctS((p.target - price) / price * 100, 1) + '</span></b></div>'
        + '<div class="kv"><span>손절선</span><b class="num">' + plPx(p.stop) + ' <span class="' + clsP((p.stop - price) / price * 100) + '">' + pctS((p.stop - price) / price * 100, 1) + '</span></b></div>'
        + '<div class="tpbar"><i style="left:' + pos + '%"></i></div>' + (p.memo ? '<div class="sub" style="margin-top:8px">' + prTxt(p.memo) + '</div>' : '') + '</div>';
    })() : '';
    const evOk = partHave('ev');
    if (!evOk) { S.partsDash = true; partsNeed(['ev'], 'dash'); }
    const evAll = evOk ? groupDayEvs(D.events.filter(e => gMatch(g, e.sym, e.pkey))).slice(0, 30) : [];
    const unitG = t => (/^[-−]?[\d,]+(\.\d+)?$/.test(String(t == null ? '' : t).trim()) && g.sym.length <= 8 ? ' ' + esc(g.sym) : '');
    const evRow = it => { const e = it.e, n = it.grp ? it.grp.length : 0, qt = it.grp ? (it.q != null ? (evXf(e) ? pvW(PVM.q) : q(it.q)) : '—') : evQ(e);
      return '<div class="kv" style="font-size:13px"><span class="num">' + esc(e.t) + '</span>' + (S.mobile ? '<span style="margin-left:0">' + evPill(e.k) + (n ? ' <span class="cap num">' + n + '건</span>' : '') + '</span>' : '<span class="ell" style="margin-left:0;font-weight:500;color:var(--text2);flex:1">' + evPill(e.k) + ' ' + esc(hs(e.d)) + (n ? ' · ' + n + '건' : '') + '</span>') + '<span class="num">' + esc(qt) + unitG(qt) + '</span></div>'; };
    const evHTML = !evOk ? '<div class="blk" style="margin-top:12px"><div class="ttl">최근 기록</div><div class="cap" role="status">불러오는 중…</div></div>' : evAll.length ? '<div class="blk" style="margin-top:12px"><div class="ttl">최근 기록 <span class="mut num pvx" style="font-weight:500">' + evAll.length + (evAll.length >= 30 ? '+' : '') + '</span></div>'
      + uiPaged('hev:' + g.key, evAll, e => evRow(e), { unit: '묶음' }) + '</div>' : '';
    const xtop = '<div class="xtop"><div class="xtk"><span class="ttl">원가 확인된 수량</span>' + (covCell(g) || '<span class="mut cvt">—</span>') + '</div>'
      + (S.mobile ? '<div class="xtk"><span class="ttl" title="' + esc(TODAY_TIP) + '">오늘 변동</span>' + todayCell(g) + '</div>' : '') + wowSlot('hold.open', g) + '</div>';
    return xtop + '<div class="xbox"><div><div class="blk"><div class="ttl">보관처별 <span class="mut" style="font-weight:500">' + g.locList.length + '곳</span>' + trChip(g.tr, g.locSummary) + '</div>' + (S.mobile ? (locRows.slice(0, 14).join('') || '<div class="mut">보관처 정보 없음</div>') : '<table class="mini-t"><thead><tr><th scope="col">보관처</th><th scope="col">수량</th><th scope="col">평가금액</th></tr></thead><tbody>' + (locRows.slice(0, 14).join('') || '<tr><td colspan="3" class="mut">보관처 정보 없음</td></tr>') + '</tbody></table>') + (locRows.length > 14 ? '<div class="sub">외 ' + (locRows.length - 14) + '곳</div>' : '') + '</div>' + evHTML + '</div>'
      + '<div><div class="blk"><div class="ttl">원가 · 토큰별' + (g.nInst > 1 ? ' <span class="mut" style="font-weight:500">토큰 ' + g.nInst + '개 합산</span>' : '') + '</div>' + (S.mobile ? inst : '<table class="mini-t"><thead><tr><th scope="col">보관처</th><th scope="col">원가</th><th scope="col">손익</th></tr></thead><tbody>' + inst + '</tbody></table>')
      + (g.nInst > 12 ? '<div class="sub">외 ' + (g.nInst - 12) + '개</div>' : '')
      + stakeNote(g) + '<div class="row" style="margin-top:10px;gap:10px;flex-wrap:wrap"><span class="cap num">원가 ' + (g.cost > 0 ? mN(g.cost) : '—') + (g.unkQty > 0 ? ' · 원가 미확인 ' + '<span class="num">' + q(g.unkQty) + '</span>' + ' ' + esc(g.sym) : '') + '</span><span class="sp"></span><button class="link" data-a="goJournalSym" data-v="' + esc(g.sym) + '">매매일지에서 보기' + IC.right + '</button></div></div>' + plan + '</div></div>';
  }
  const futSym = s => { const b = String(s || '').replace(/[-_/]?(USDT|USDC|USD)([-_]?(SWAP|PERP|M))?$/i, ''); return (b || s) + ' 무기한'; };
  const upnlH = (v, why, o) => v == null ? '<span class="mut" title="' + esc(why || '코인 정산 — 시세가 없어 달러로 못 바꿈') + '">—</span>' : m(num(v), o);
  const SUB_SFX = / · 서브[1-9]$/;
  const exKey = ex => { const x9 = String(ex || '').replace(SUB_SFX, ''), e = x9.toLowerCase(); return EX_NAMES[e] ? e : (EX_BY_KO[x9] || e); };
  const exNm = ex => { const m9 = String(ex || '').match(SUB_SFX); return (EX_NAMES[exKey(ex)] || String(ex || '').replace(SUB_SFX, '')) + (m9 ? m9[0] : ''); };
  function futPosHTML(side) {
    const f = S.D.fut, ps = arr(f.positions);
    if (!ps.length) return '';
    return '<div class="card' + (side ? ' sidec' : '') + '"><div class="tblhead"><h2 class="h2">선물 포지션</h2><span class="cap num">' + ps.length + '개 · 마크가 기준' + (side ? '' : ' · 총자산 미반영') + '</span><div class="sp"></div><button class="link" data-a="openFut">상세' + IC.right + '</button></div>'
      + (S.mobile || side ? '<div class="m-list">' + ps.map(p => '<div class="it">' + icon(p.sym, true) + '<div class="ell"><div class="sym">' + esc(futSym(p.sym)) + ' <span class="pill ' + (p.side === 'LONG' ? 'up' : 'down') + ' sm">' + esc(p.side === 'LONG' ? '롱' : '숏') + (p.lev ? ' ×' + esc(p.lev) : '') + '</span></div><div class="sub">' + esc(exNm(p.ex)) + (p.dex ? ' <span class="pill g sm">덱스</span>' : '') + ' · ' + q(num(p.qty)) + '</div></div><div class="r"><div class="val num ' + cls(num(p.upnl)) + '">' + upnlH(p.upnl, p.upnlWhy, { sign: true }) + '</div><div class="sub num">' + (num(p.liq) > 0 && p.liqDist != null ? '청산까지 ' + Math.abs(num(p.liqDist)).toFixed(1) + '%' : '청산가 없음') + '</div></div></div>').join('') + '</div>'
        : '<table><thead><tr><th scope="col">포지션</th><th scope="col">수량</th><th scope="col">진입 / 마크</th><th scope="col">평가손익</th><th scope="col">청산까지</th></tr></thead><tbody>' + ps.map(p => {
          const d9 = num(p.liq) > 0 && p.liqDist != null ? Math.abs(num(p.liqDist)) : null;
          return '<tr><td><div class="asset">' + icon(p.sym, true) + '<div><div class="sym">' + esc(futSym(p.sym)) + ' <span class="pill ' + (p.side === 'LONG' ? 'up' : 'down') + ' sm">' + esc(p.side === 'LONG' ? '롱' : '숏') + (p.lev ? ' ×' + esc(p.lev) : '') + '</span></div><div class="sub row gap6">' + exLogo(exKey(p.ex)) + esc(exNm(p.ex)) + (p.dex ? '<span class="pill g sm">덱스</span>' : '') + '</div></div></div></td><td class="num">' + q(num(p.qty)) + '</td><td class="num">' + px(num(p.entry)) + '<div class="sub">' + px(num(p.mark)) + '</div></td><td class="num ' + cls(num(p.upnl)) + '" style="font-weight:700">' + upnlH(p.upnl, p.upnlWhy, { sign: true }) + '</td><td class="num">' + (d9 == null ? '<span class="mut">없음</span>' : '<span style="color:' + (d9 < 10 ? 'var(--danger)' : d9 < 25 ? 'var(--warn)' : 'var(--text2)') + '">' + d9.toFixed(1) + '%</span><div class="sub">' + px(num(p.liq)) + '</div>') + '</td></tr>';
        }).join('') + '</tbody></table>') + '</div>';
  }
  const pxrRaw = v => (v >= 1000 ? nf('en-US', null, 0).format(v) : v >= 1 ? trimZeros(v.toFixed(4)) : trimZeros(v.toPrecision(4)));
  const pxr = v => S.hide ? pvW(PVM.px) : rw(pxrRaw(v));
  function lpRangeBar(l) {
    const lo = l.lo, hi = l.hi, pr = l.price;
    if (!(lo > 0 && hi > lo)) return l.rangeText ? '<div class="sub num">' + esc(S.hide ? pvW(PVM.px) : l.rangeText) + '</div>' : '';
    const span = hi - lo, pad = span * 0.25, a = lo - pad, b = hi + pad;
    const X = v => Math.max(0, Math.min(100, (v - a) / (b - a) * 100));
    const col = l.state === 'in' ? 'var(--ok)' : 'var(--warn)';
    return '<div class="lprng" title="범위 ' + esc(pxr(lo)) + ' ~ ' + esc(pxr(hi)) + (pr > 0 ? ' · 현재 ' + esc(pxr(pr)) : '') + '"><span class="band" style="left:' + X(lo) + '%;width:' + (X(hi) - X(lo)) + '%;background:color-mix(in srgb,' + col + ' 28%,transparent)"></span>'
      + (pr > 0 ? '<i style="left:' + X(pr) + '%;background:' + col + '"></i>' : '') + '</div>'
      + '<div class="sub num lprl"><span>' + esc(pxr(lo)) + '</span><span>' + (pr > 0 ? '<b style="color:var(--text)">' + esc(pxr(pr)) + '</b>' : '') + '</span><span>' + esc(pxr(hi)) + '</span></div>';
  }
  function lpStatePill(l) {
    return l.state === 'closed' ? '<span class="pill g sm">종료</span>' : l.state === 'in' ? '<span class="pill ok sm">범위 내</span>' : l.state === 'out' ? '<span class="pill w sm">범위 이탈</span>' : '<span class="pill g sm">확인 중</span>';
  }
  const lpShortProto = p => String(p || '').replace(/^Uniswap\s+/i, 'Uni ').replace(/^PancakeSwap\s+/i, 'Pancake ').replace(/^SushiSwap\s+/i, 'Sushi ').replace(/\s+Slipstream$/i, ' CL').replace(/\sV(\d)$/, ' v$1');
  const lpBadge = l => (l.protocol ? ' <span class="pill g sm lpb" title="' + esc(l.protocol) + '">' + esc(lpShortProto(l.protocol)) + '</span>' : '') + (l.staked ? ' <span class="pill a sm" title="' + esc('스테이킹 위치 ' + l.staked) + '">스테이킹</span>' : '');
  const lpIcon = (l, sz) => { const s = l.syms.length >= 2 ? l.syms : [l.pool]; return '<span class="pair">' + s.slice(0, 2).map(x => icon(x, sz || 'sm', { chain: '' })).join('') + '</span>'; };
  function lpDetail(l) {
    const D = S.D;
    const evs = D.events.filter(e => e.lp === l.key).slice(0, 10);
    const kv = (a, b) => '<div class="kv"><span>' + a + '</span><b class="num">' + b + '</b></div>';
    return '<div class="xbox"><div><div class="blk"><div class="ttl">포지션 <span class="pill g sm">읽기 전용</span></div>'
      + kv('프로토콜', esc(l.protocol || '—')) + kv('체인', esc(l.chain || '—')) + (l.fee ? kv('수수료 등급', esc(l.fee)) : '') + (l.id ? kv('포지션 ID', '#' + esc(l.id)) : '') + (l.staked ? kv('스테이킹', esc(String(l.staked).slice(0, 6) + '…' + String(l.staked).slice(-4))) : '')
      + kv('예치 · 최근', esc(l.opened || '—') + ' · ' + esc(l.last || '—'))
      + (l.price > 0 ? kv('현재가', esc(pxr(l.price)) + ' ' + esc(l.quote)) : '') + (l.lo > 0 ? kv('범위', esc(pxr(l.lo)) + ' ~ ' + esc(pxr(l.hi)) + ' ' + esc(l.quote)) : '')
      + (l.apr ? kv('APR', esc(l.apr)) : '') + (l.il != null ? kv('무상손실', '<span class="' + cls(l.il) + '">' + m(l.il, { sign: true }) + '</span>') : '') + '</div>'
      + '<div class="blk" style="margin-top:12px"><div class="ttl">구성</div>' + (l.amounts.length ? l.amounts.map(a => kv(esc(a.sym), (a.amt == null ? '<span class="mut">구성 미확인</span>' : (a.lt ? '&lt;' : '') + lpAmt(a)) + (a.then != null ? ' <span class="cap">(예치 ' + esc(S.hide || S.rand ? hq(a.then) : a.then) + ')</span>' : ''))).join('') : '<div class="mut" style="font-size:13px">온체인 구성 수집 대기</div>')
      + (l.feeAmts.length ? '<div class="sub" style="margin-top:6px">미청구 ' + l.feeAmts.map(a => q(a.amt) + ' ' + esc(a.sym)).join(' + ') + '</div>' : '') + '</div></div>'
      + '<div><div class="blk"><div class="ttl">원가 · 손익</div>'
      + (l.noLedger ? '<div class="fbnote" style="margin-top:0">원장에 예치 기록이 없는(수집 창 이전) 포지션 — 원가 미확인</div>' : '')
      + kv('누적 예치', l.deposit != null ? m(l.deposit) : '—') + (l.state === 'closed' ? kv('수수료 수익', l.income ? '<span class="' + clsV(KV(l.income, Math.abs(l.income - l.realized) < 0.01 ? l.realizedK : null)) + '">' + m(KV(l.income, Math.abs(l.income - l.realized) < 0.01 ? l.realizedK : null), { sign: true }) + (l.deposit > 0 ? ' (' + pctS(l.income / l.deposit * 100, 2) + ')' : '') + '</span>' : '—') : kv('미회수 원금', l.principal != null ? m(l.principal) : '—'))
      + (l.state === 'closed' ? kv('현재 가치', '<span class="mut">인출 완료</span>') : kv('현재 가치', l.value != null ? m(l.value) : '<span class="mut">평가 불가</span>')) + kv('미청구 수수료', l.fees != null ? m(l.fees) : '—') + (l.rewards ? kv('리워드', m(l.rewards)) : '')
      + kv('평가손익', l.pnl != null ? '<span class="' + cls(l.pnl) + '">' + m(l.pnl, { sign: true }) + (l.pnlPct != null ? ' (' + pctS(l.pnlPct, 1) + ')' : '') + '</span>' : '—')
      + (l.state === 'closed' && l.income && Math.abs(l.income - l.realized) < 0.01 ? '' : kv('실현 (인출분)', l.realized ? '<span class="' + clsV(KV(l.realized, l.realizedK)) + '">' + m(KV(l.realized, l.realizedK), { sign: true }) + '</span>' : '—')) + '</div>'
      + '<div class="blk" style="margin-top:12px"><div class="ttl">LP 이벤트</div>' + (evs.map(e => '<div class="kv" style="font-size:13px"><span class="num">' + esc(e.t) + '</span><span class="ell" style="margin-left:0;flex:1;font-weight:500;color:var(--text2)">' + evPill(e.k) + ' ' + esc(hs(e.d)) + '</span><span class="num">' + evA(e) + '</span></div>').join('') || '<div class="mut" style="font-size:13px">기록 없음</div>') + '</div></div></div>';
  }
  const lpAmt = a => (S.rand && a.lt ? pvW(PVM.q) : q(a.amt));
  const LP_TOP = 2;
  const lpWorth = l => num(l.value) + num(l.fees) + num(l.rewards);
  const lpSorted = ls => ls.map((l, i) => [l, i]).sort((a, b) => lpWorth(b[0]) - lpWorth(a[0]) || a[1] - b[1]).map(x => x[0]);
  const lpName = l => esc(l.pool) + (l.id ? ' <span class="lpid num">#' + esc(l.id) + '</span>' : '');
  const LP_IC = '<svg class="lvic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>';
  function lpCardHTML() {
    const D = S.D, mob = S.mobile;
    const live = lpSorted(arr(D.lps).filter(l => l.state !== 'closed')), closed = arr(D.lpsClosed);
    if (!live.length && !closed.length) return '';
    const cOn = !!S.lpClosed && closed.length > 0;
    const cDates = l => { const lt = num((l.raw || {}).lastTs); return esc(l.opened || '—') + (lt > 0 ? ' ~ ' + esc(fmtTs(lt).slice(0, 5)) : ''); };
    const cReal = l => num(l.realized) ? '<b class="num ' + clsV(KV(l.realized, l.realizedK)) + '" title="' + esc(m(KV(l.realized, l.realizedK), { sign: true })) + '">' + m(KV(l.realized, l.realizedK), { sign: true, compact: true }) + '</b>' : '<b class="mut">—</b>';
    const tap = (l, open) => ' role="button" tabindex="0" data-a="lpTog" data-k="' + esc(l.key) + '" aria-expanded="' + open + '"';
    const row = l => {
      const open = S.lpOpen.has(l.key), cl = l.state === 'closed';
      if (mob) {
        const st = '<span class="lpst st-' + esc(l.state) + '">' + esc(l.stateLabel || '') + '</span>';
        const r = cl ? '<b class="mut">인출 완료</b><span>' + (num(l.realized) ? '실현 ' + cReal(l) : '<span class="mut">실현 없음</span>') + '</span>'
          : '<b' + (l.value != null ? ' class="num">' + m(l.value) : '><span class="mut">평가 불가</span>') + '</b><span>' + (l.pnl != null ? '<span class="num ' + cls(l.pnl) + '">' + m(l.pnl, { sign: true, compact: true }) + '</span>' : '원가 미확인') + ' · 미청구 <span class="num">' + (l.fees != null ? m(l.fees, { compact: true }) : '—') + '</span></span>';
        return '<div class="lpm' + (cl ? ' lpc' : '') + (open ? ' open' : '') + '"' + tap(l, open) + '>' + lpIcon(l) + '<span class="lpnm"><b>' + lpName(l) + '</b><span class="cap">' + st + ' · ' + esc([lpShortProto(l.protocol), l.chain].filter(Boolean).join(' · ')) + (cl ? ' · ' + cDates(l) : l.staked ? ' · 스테이킹' : '') + '</span></span><span class="lpmr">' + r + '</span></div>'
          + (open ? clps('lp:' + l.key, '<div class="lpx">' + (cl ? '' : lpRangeBar(l)) + lpDetail(l) + '</div>') : '');
      }
      const nm = '<div class="lpn">' + lpIcon(l) + '<div class="lpnm"><b>' + lpName(l) + '</b><span class="cap">' + (lpBadge(l).trim() + ' ' + esc([l.chain, l.fee].filter(Boolean).join(' · '))).trim() + '</span></div></div>';
      const cells = cl
        ? '<div class="lprg">' + lpStatePill(l) + '<span class="cap num">' + cDates(l) + '</span></div>'
          + '<div class="lpv"><b class="mut">인출 완료</b><span class="cap">예치 ' + (l.deposit != null ? m(l.deposit, { compact: true }) : '—') + '</span></div>'
          + '<div class="lpv lpf"><b class="mut">—</b></div>'
          + '<div class="lpv lpp">' + cReal(l) + '<span class="cap">' + (num(l.realized) ? '실현' : '실현 없음') + '</span></div>'
        : '<div class="lprg">' + lpStatePill(l) + lpRangeBar(l) + '</div>'
          + '<div class="lpv"><b' + (l.value != null ? ' class="num">' + m(l.value) : '><span class="mut">평가 불가</span>') + '</b><span class="cap">원가 ' + (l.principal != null ? m(l.principal) : '미확인') + '</span></div>'
          + '<div class="lpv lpf"><span class="lpl">미청구 수수료</span><b class="num">' + (l.fees != null ? m(l.fees) : '—') + '</b>' + (l.rewards ? '<span class="cap">리워드 ' + m(l.rewards) + '</span>' : '') + '</div>'
          + '<div class="lpv lpp"><span class="lpl">평가손익</span><b class="num ' + cls(l.pnl) + '">' + (l.pnl != null ? m(l.pnl, { sign: true }) : '—') + '</b><span class="cap ' + cls(l.pnl) + '">' + (l.pnlPct != null ? pctS(l.pnlPct, 1) : '') + '</span></div>';
      return '<div class="lpr' + (cl ? ' lpc' : '') + (open ? ' open' : '') + '"' + tap(l, open) + '>' + nm + cells + '</div>'
        + (open ? clps('lp:' + l.key, '<div class="lpx">' + lpDetail(l) + '</div>') : '');
    };
    const nLive = '<span class="lvp pvx">운용 중 ' + live.length + '</span>', ord = live.length > 1 ? '<span class="cap lpord">가치 큰 순</span>' : '';
    const hd = mob
      ? '<div class="lvh"><h2>LP 포지션</h2>' + (live.length ? nLive : '<span class="cap">운용 중인 포지션 없음</span>') + '<span class="sp"></span>' + ord + '</div>'
        + (live.length ? '<div class="lpsum cap">가치 <b class="num">' + m(D.lpValue) + '</b> · 미청구 <span class="num">' + m(D.lpFees + D.lpRewards) + '</span></div>' : '')
      : '<div class="lvh">' + LP_IC + '<h2>LP 포지션</h2>' + (live.length ? nLive + '<span class="lvp num">가치 ' + m(D.lpValue) + '</span><span class="lvp num">미청구 ' + m(D.lpFees + D.lpRewards) + '</span>' + ord : '<span class="cap">운용 중인 포지션 없음</span>')
        + '<span class="sp"></span>' + (closed.length ? '<button type="button" class="link lpcl" data-a="lpClosed" aria-expanded="' + cOn + '">' + (cOn ? '종료된 포지션 숨기기<span class="uchev up" aria-hidden="true">' + IC.chev + '</span>' : '<span class="pvx">종료된 포지션 ' + closed.length + '개</span>' + IC.right) + '</button>' : '') + '</div>';
    const restV = sum(live.slice(LP_TOP), l => num(l.value));
    const more = live.length > LP_TOP ? uiPaged('lp:dash', live.slice(LP_TOP), l => row(l), { unit: '개', cls: 'lvmore', more: rest => '<span class="pvx">' + rest + '개 더</span>'
      + (mob ? '' : ' · ' + live.slice(LP_TOP, LP_TOP + 2).map(l => esc(l.pool)).join(' · ') + (rest > 2 ? ' 외' : '')) + ' · 합 <span class="num">' + m(restV) + '</span>' }) : '';
    const cols = mob ? '' : '<div class="lpr lphd" aria-hidden="true"><span>풀</span><span>범위 · 현재가</span><span class="lpv">현재 가치</span><span class="lpv lpf">미청구 수수료</span><span class="lpv lpp">평가손익</span></div>';
    const rows = live.length ? '<div class="lprows">' + cols + live.slice(0, LP_TOP).map(row).join('') + more + '</div>' : '';
    const cSum = sum(closed, l => num(l.realized));
    const cProto = (() => { const c = new Map(); closed.forEach(l => { const k = lpShortProto(l.protocol) || 'LP'; c.set(k, (c.get(k) || 0) + 1); }); return Array.from(c.entries()).sort((a, b) => b[1] - a[1]).map(([k, n]) => '<span class="pill g sm lpb">' + esc(k) + ' ' + n + '</span>').join(' '); })();
    const cLine = closed.length ? '<div class="lpcs"><span class="cap"><span class="pvx">종료된 포지션 ' + closed.length + '개' + (mob ? '' : ' · 인출 완료') + '</span>' + (cSum && (cOn || !mob) ? ' · 실현 합 ' + m(cSum, { sign: true, compact: true }) : '') + '</span>'
      + (mob ? '' : '<span class="lpcp pvx">' + cProto + '</span>') + '<span class="sp"></span><button type="button" class="link" data-a="lpClosed" aria-expanded="' + cOn + '">' + (cOn ? '숨기기' : '보기') + '</button></div>' : '';
    const cl = !closed.length ? '' : mob ? cLine + (cOn ? '<div class="lprows lpcrows">' + closed.map(row).join('') + '</div>' : '') : cOn ? '<div class="lprows lpcrows">' + cLine + closed.map(row).join('') + '</div>' : '';
    return '<section class="card lpk' + (live.length ? '' : ' lpone') + (mob ? ' lpmob' : '') + '" aria-label="LP 포지션">' + hd + rows + cl + '</section>';
  }
  function venuesHTML() {
    const D = S.D;
    const all = D.venues, vis = all.filter(v => S.dust <= 0 || v.total >= S.dust);
    const mx = vis.length ? vis[0].total : 1;
    const pgV = uiPgSlice('venue', vis);
    return '<div class="card box"><div class="row"><h2 class="h2">보관처별</h2><div class="sp"></div><span class="cap">현금 포함 · ' + vis.length + '곳' + (all.length > vis.length ? ' · 소액 ' + (all.length - vis.length) + '곳 숨김' : '') + '</span></div>'
      + (pgV.last > 0 ? '<div class="upga" data-pga="venue"></div>' : '') + '<div class="cust">' + (pgV.rows.map(v => {
        const vk = nmKey(v.name);
        const lg = v.kind === 'lp' ? '<span class="exl w" aria-hidden="true">' + IC.layers + '</span>' : venueLogo(v.name);
        return '<div class="it"><button data-a="venueOpen" data-k="' + esc(vk) + '" aria-haspopup="dialog"><div class="top2">' + lg + '<span class="ell pvl">' + esc(locName(v.name)) + '</span><b class="num" data-fl="v:' + esc(vk) + '" data-v="' + (S.hide || S.rand ? 0 : v.total.toFixed(2)) + '">' + m(v.total, { compact: true }) + '</b></div>'
          + '<div class="mini"><i style="width:' + Math.max(1, v.total / mx * 100).toFixed(1) + '%;background:' + (v.kind === 'wallet' ? 'var(--c4)' : v.kind === 'lp' ? 'var(--c3)' : 'var(--accent)') + '"></i></div></button></div>';
      }).join('') || '<div class="mut" style="font-size:14px;padding:10px 0">보관처가 없어요</div>') + '</div>'
      + uiPgBar('venue', vis.length, { unit: '곳' }) + '</div>';
  }
  const vnCash = sym => { const s = String(sym || '').toUpperCase(); return s === 'KRW' || !!(S.D && S.D.stableSyms && S.D.stableSyms.has(s)); };
  const VN_FAM = { Solana: 'SOL', Tron: 'TRON', Sui: 'SUI', TON: 'TON', Bitcoin: 'BTC' }, VN_FAMS = ['EVM', 'SOL', 'TRON', 'SUI', 'TON', 'BTC'];
  function vnModel(v) {
    const D = S.D, tot = num(v.total);
    const cm = new Map();
    v.items.forEach(it => { const k = String(it.sym || '?'); let c = cm.get(k); if (!c) { c = { sym: k, usd: 0, qty: 0, qn: true, lbl: null }; cm.set(k, c); }
      c.usd += num(it.usd); if (typeof it.qty === 'number') c.qty += it.qty; else { c.qn = false; c.lbl = it.qty; } });
    const coins = Array.from(cm.values()).sort((a, b) => b.usd - a.usd || (a.sym < b.sym ? -1 : 1));
    coins.forEach(c => { c.pct = tot > 0 ? Math.max(0, c.usd) / tot * 100 : 0; });
    const chm = new Map();
    v.items.forEach(it => { const ch = String(it.ch || ''); if (!ch) return; chm.set(ch, (chm.get(ch) || 0) + num(it.usd)); });
    const chains = Array.from(chm.entries()).map(([ch, usd]) => ({ ch, usd, pct: tot > 0 ? Math.max(0, usd) / tot * 100 : 0 })).sort((a, b) => b.usd - a.usd);
    const addrs = [], chAddr = {};
    if (v.kind === 'wallet') {
      const W = arr(D.wallets);
      v.items.forEach(it => { const p9 = String(it.sub || '').split(' · '), ch9 = String(it.ch || p9[0] || ''); if (!p9.some(t => t.indexOf('…') > 0)) return;
        const w = W.find(x => { const a = String(x.addr || ''), s9 = short(a); return !!a && p9.some(t => /^0x/i.test(a) ? s9.toLowerCase() === t.toLowerCase() : s9 === t); }); if (!w) return;
        if (addrs.indexOf(w.addr) < 0) addrs.push(w.addr);
        if (ch9 && !chAddr[ch9]) chAddr[ch9] = w.addr; });
    }
    const allCash = v.kind !== 'lp' && v.items.length > 0 && v.items.every(it => vnCash(it.sym));
    const fam9 = new Set(chains.map(c => VN_FAM[c.ch] || 'EVM'));
    const kindTxt = v.kind === 'wallet' ? '지갑 · ' + (VN_FAMS.filter(f => fam9.has(f)).join(' · ') || 'EVM') : v.kind === 'lp' ? 'LP' : allCash ? '현금' : '거래소';
    const share = num(D.total) > 0 ? tot / num(D.total) * 100 : 0;
    return { v, tot, coins, chains, addrs, chAddr, kindTxt, share };
  }
  function vnExpl(ch, addr) { const k = CHAIN_KEY[ch]; return k && EXPL[k] && addr && !S.rand ? EXPL[k][1] + encodeURIComponent(addr) : null; }
  const vnBar = p => (Math.abs(num(p)) < 1 ? '' : '<div class="mini" aria-hidden="true"><i style="width:' + Math.min(100, Math.max(0, num(p))).toFixed(1) + '%"></i></div>');
  const vnPct = p => '<span class="num vnp">' + Math.round(num(p)) + '%</span>';
  function vnFlows(M) {
    const F = S.D.vflows, v = M.v, by = F && F.by ? F.by[v.name] : null, Z = { in: 0, out: 0, realized: 0, realizedKrw: 0 };
    const okF = !!(F && F.flowOk && v.kind !== 'lp'), okR = !!(F && v.kind !== 'lp'), x = by || Z;
    const rec = vnSrc(M);
    const rzV = KV(num(x.realized), x.realizedKrw != null ? num(x.realizedKrw) : null);
    const dash = '<span class="mut">—</span>';
    return '<section class="vnsec vnfl"><div class="vnh"><b>드나든 돈 · 최근 30일</b>' + (rec ? '<button class="link" data-a="venueRec">이곳 기록 보기 ›</button>' : '') + '</div><div class="vntiles">'
      + uiCell('들어옴', okF ? '<span class="' + (num(x.in) > 0 ? 'up' : '') + '">' + (num(x.in) > 0 ? '+' : '') + m(num(x.in), { compact: true }) + '</span>' : dash)
      + uiCell('나감', okF ? '<span class="' + (num(x.out) > 0 ? 'down' : '') + '">' + (num(x.out) > 0 ? '−' : '') + m(num(x.out), { compact: true }) + '</span>' : dash)
      + uiCell('이곳 매매 실현', okR ? '<span class="' + clsV(rzV) + '">' + m(rzV, { sign: true, compact: true }) + '</span>' : dash)
      + '</div></section>';
  }
  function vnSrc(M) {
    const v = M.v;
    if (v.kind === 'wallet') { const k = M.addrs.length === 1 ? (S.D.walletAlias && Object.keys(S.D.walletAlias).find(a => a.toLowerCase() === M.addrs[0].toLowerCase())) || M.addrs[0] : ''; return k ? { mode: 'dex', key: k } : null; }
    if (v.kind === 'cex') { const k = EX_BY_KO[v.name] || EX_BY_KO[String(v.name).replace(/ .*$/, '')]; return k ? { mode: 'cex', key: k } : null; }
    return null;
  }
  function vnChains(M) {
    const v = M.v;
    if (v.kind !== 'wallet' || !M.chains.length) return '';
    const anyL = M.chains.some(c => vnExpl(c.ch, M.chAddr[c.ch]));
    const rows = M.chains.map(c => { const u = vnExpl(c.ch, M.chAddr[c.ch]);
      const nm = u ? '<a class="ell vnchn" href="' + esc(TJDOM.safeUrl(u)) + '" target="_blank" rel="noopener noreferrer" title="' + esc(c.ch + ' 탐색기에서 보기') + '">' + esc(c.ch) + '</a>' : '<span class="ell vnchn">' + esc(c.ch) + '</span>';
      return '<div class="it vnch"><div class="top2">' + nm + '<b class="num">' + m(c.usd, { compact: true }) + '</b>' + vnPct(c.pct) + '</div>' + vnBar(c.pct) + '</div>'; }).join('');
    const ad = M.addrs.map(a => '<div class="vnad"><span class="mono">' + esc(short(a)) + '</span><span class="sp"></span>' + copyBtn(a) + '</div>').join('');
    return '<section class="vnsec"><div class="vnh"><b>체인별</b>' + (anyL ? '<span class="cap">이름 누르면 탐색기</span>' : '') + '</div><div class="cust vnl">' + rows + '</div>' + (ad ? '<div class="vnads">' + ad + '</div>' : '') + '</section>';
  }
  function vnCoins(M) {
    const all = M.coins, vk9 = 'vnco:' + nmKey(M.v.name), pgC = uiPgSlice(vk9, all), shown = pgC.rows;
    const row = c => { const lg = S.D.symLogo && S.D.symLogo[c.sym];
      const qt = c.qn ? q(c.qty) : c.lbl && c.lbl.krw != null ? krw(c.lbl.krw) : esc(String(c.lbl == null ? '' : c.lbl));
      const go = c.sym !== 'KRW' && M.v.kind !== 'lp';
      return '<div class="it vnco"><' + (go ? 'button type="button" data-a="venueCoin" data-v="' + esc(c.sym) + '"' : 'div') + ' class="vnrow"><div class="top2">' + icon(c.sym, '', lg ? { ck: lg.ck, ca: lg.ca } : {})
        + '<span class="vncn ell"><span class="vnsym">' + esc(c.sym) + '</span> <span class="num mut">' + qt + '</span></span><b class="num">' + m(c.usd, { compact: true }) + '</b>' + vnPct(c.pct) + '</div>'
        + vnBar(c.pct) + '</' + (go ? 'button' : 'div') + '></div>'; };
    const more = uiPgBar(vk9, all.length, { unit: '종' });
    return '<section class="vnsec vncs">' + (pgC.last > 0 ? '<div class="upga" data-pga="' + esc(vk9) + '"></div>' : '') + '<div class="vnh"><b>들어 있는 코인</b>' + (M.v.kind !== 'lp' ? '<span class="cap">눌러서 보유표로</span>' : '') + '</div><div class="cust vnl">' + shown.map(row).join('') + '</div>' + more + '</section>';
  }
  function venueDrawer() {
    const D = S.D, v = arr(D.venues).find(x => nmKey(x.name) === S.venueK);
    const close = '<button class="iconbtn" data-a="drawerClose" aria-label="닫기">' + IC.close + '</button>';
    if (!v) return '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer venue" role="dialog" aria-modal="true" aria-label="보관처 상세"><div class="dh"><h2 class="h2">보관처 상세</h2><span class="sp"></span>' + close + '</div><div class="cap" role="status">이 보관처는 지금 목록에 없어요(잔고 0 · 이름 바뀜)</div></aside>';
    const M = vnModel(v);
    const exTs = (D.exBalTs || {})[v.name];
    const meta = v.kind === 'wallet' ? '코인 ' + M.coins.length + '종 · 체인 ' + M.chains.length + '개 · ' + scanText(D.lastScan) + ' 수집'
      : v.kind === 'cex' ? '코인 ' + M.coins.length + '종 · ' + (exTs ? '잔고 기준 ' + ago(exTs) : '잔고 시각 모름') : '포지션 ' + M.coins.length + '개';
    const share = (M.share < 0 ? '−' : '') + (Math.abs(M.share) >= 0.5 || M.share === 0 ? Math.round(Math.abs(M.share)) : '<1') + '%';
    return '<div class="drawer-bg" data-a="drawerClose"></div><aside class="drawer venue" role="dialog" aria-modal="true" aria-label="보관처 상세">'
      + '<div class="dh"><h2 class="h2 vnt ell pvl">' + esc(locName(v.name)) + '</h2><span class="pill sm vnkind">' + esc(M.kindTxt) + '</span><span class="sp"></span>' + close + '</div>'
      + '<section class="vnhero"><span class="cap">이곳에 있는 돈 · 총자산의 <span class="num">' + esc(share) + '</span></span><b class="num vnbig">' + m(M.tot, { compact: true }) + '</b><span class="num mut vnalt">' + mAlt(M.tot) + '</span><span class="cap pvx vnmeta">' + esc(meta) + '</span></section>'
      + vnFlows(M) + vnChains(M) + vnCoins(M) + '</aside>';
  }
  function venueOpen(el) {
    const ae = el || document.activeElement;
    S.venueBack = ae && ae.getAttribute && ae.getAttribute('data-a') ? { el: ae, a: ae.getAttribute('data-a'), v: ae.getAttribute('data-v'), k: ae.getAttribute('data-k') } : null;
    S.venueK = String((el && el.dataset && el.dataset.k) || ''); delete uiPgS()['vnco:' + S.venueK];
    S.drawer = 'venue'; S.pop = null;
    drawerHist();
    renderOverlay();
    { const b = $('#overlay .drawer [data-a="drawerClose"]'); if (b) b.focus(); }
  }
  const CASH_LOC_MIN = 0.01;
  function cashHTML() {
    const D = S.D;
    const st = D.stableGroups.filter(g => dustOk(g.value));
    const fi = D.fiats.filter(x => dustOk(num(x.krw) / D.rate));
    if (!st.length && !fi.length) return '';
    const liveL = g => g.locs.filter(l => !(num(l.value) < CASH_LOC_MIN));
    const fiV = x => S.hide ? (S.cur === 'USD' ? '$' + pvW(PVM.usdC) : '₩' + pvW(PVM.krwC)) : S.cur === 'USD' ? m(num(x.krw) / D.rate, { compact: true }) : '₩' + rw(eok(KS(num(x.krw))));
    return '<div class="card box"><div class="row"><h2 class="h2">현금성</h2><div class="sp"></div><b class="num">' + m(D.cashTotal, { compact: true }) + '</b></div><div class="cust">'
      + st.map(g => { const open = S.stOpen.has(g.sym); return '<div class="it" data-anc="cash:' + esc(g.sym) + '"><button data-a="stTog" data-k="' + esc(g.sym) + '" aria-expanded="' + open + '"><div class="top2">' + icon(g.sym, 'xs', { noSym: false }) + '<span>' + esc(g.sym) + trChip(g.tr, '', true) + '</span><span class="sub"' + (g.locs.length > liveL(g).length ? ' title="' + esc('잔고 1센트 미만 ' + (g.locs.length - liveL(g).length) + '곳 제외') + '"' : '') + '>' + liveL(g).length + '곳</span><b class="num" title="' + esc(m(g.value)) + '">' + m(g.value, { compact: true }) + '</b></div></button>'
        + (open ? clps('st:' + g.sym, '<div class="items">' + g.locs.slice().sort((a, b) => b.value - a.value).slice(0, 10).map(l => '<div><span class="ell">' + locH(l.w) + trChip(l.tr, l.w) + ' <span class="mut' + (l.tr ? ' trs' : '') + '">' + esc(l.sub) + '</span></span><span class="num">' + q(l.qty) + '</span></div>').join('') + '</div>') : '') + '</div>'; }).join('')
      + fi.map(x => '<div class="it"><div class="top2">' + venueLogo(x.ex) + '<span>' + esc(x.ex) + ' 원화</span><span class="sub">' + esc(x.note || '') + '</span><b class="num" title="' + esc(krw(num(x.krw)) + (S.cur === 'USD' ? ' · ' + m(num(x.krw) / D.rate) : '')) + '">' + fiV(x) + '</b></div></div>').join('')
      + '</div></div>';
  }
  function pendSplitTxt() {
    const D = S.D, rec = D.pendVis.length - D.unkhRows.length;
    return [rec ? '미매칭 기록 ' + rec + '건' : '', D.unkhSymN ? '원가 미확인 보유 ' + D.unkhSymN + '종' : ''].filter(Boolean).join(' + ');
  }
  function watchHTML() {
    const D = S.D;
    const rows = D.merged.filter(p => p.held > 0 && D.plans[p.key]);
    if (!rows.length) return '';
    return '<div class="card box"><div class="row"><h2 class="h2">목표 · 손절 감시</h2><div class="sp"></div><span class="cap">1분 간격</span></div><div class="cust">'
      + uiPaged('watch', rows, p => {
        const pl = D.plans[p.key], price = p._price, span = pl.target - pl.stop;
        const pos = span > 0 && price > 0 ? Math.max(2, Math.min(98, (price - pl.stop) / span * 100)) : 50;
        const toT = price > 0 ? (pl.target - price) / price * 100 : null;
        return '<div class="it"><button data-a="goJournalSym" data-v="' + esc(p.sym) + '"><div class="top2"><span><b>' + esc(p.sym) + '</b> <span class="sub">' + pxC(price) + '</span></span><b class="num ' + (toT != null && toT < 8 ? 'up' : 'mut') + '">' + pctS(toT, 1) + '</b></div>'
          + '<div class="tpbar"><i style="left:' + pos + '%"></i></div><div class="row sub num"><span>손절 ' + plPx(pl.stop) + '</span><span class="sp"></span><span>목표 ' + plPx(pl.target) + '</span></div></button></div>';
      }, { unit: '개' }) + '</div></div>';
  }
  return {
    attBars, attCore, attdActs, attdPurge, attItems, attLine, attOf, BENCH_K, benchLoad, benchSet, bindChart, exKey, exLinked, flowSplit, flowTip,
    fsKchip, futSym, gMatch, habitsHTML, habLoad, heroNums, histLoad, holdPgHit, holdRows, lpDetail, lpIcon, lpStatePill, monthRealized, ONB_X,
    onbHidden, onbState, pendSplitTxt, planOfGroup, preData, pxr, sparkSVG, SUB_SFX, todayD, upnlH, vDash, venueDrawer, venueOpen, vnModel, vnSrc,
    __late
  };
};
