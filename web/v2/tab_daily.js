'use strict';
(window.__tjTabs = window.__tjTabs || {}).daily = function (X) {
  const {
    $, arr, attBars, attCore, attLine, attOf, CAL_DOT_USD, calTint, cls, clsV, dayCnt, dayFlowV, dayFull, dayV, dayWait, DOWS, esc, evA, evAK, evDH,
    evDT, evNm, evPill, evQ, evSkel, evXf, EX_NAMES, flowSplit, flowTip, hs, IC, icon, impChip, isISO, isoDay, isYMD, isZ, kimpChip, kimpCol,
    krwDayHTML, KV, lpNm, lpNmHTML, LS, m, mcal, mN, monthRealized, nf, num, optCk, pad2, parseMoney, pctS, plainT, popBox, prTxt, PVM, pvMoney, pvOn,
    pvW, q, rate, revTxt, rfrTag, rollMinISO, S, short, srcBtn, srcPass, sum, term, todayD, todayISO, UI_SHEETS, uiFold, uiPaged, uiPgBar, uiPgSlice,
    ymOf, ymShift
  } = X;
  let A, mAlt;
  const __late = L => {
    if ('A' in L) A = L.A;
    if ('mAlt' in L) mAlt = L.mAlt;
  };
  const SENT = { '양호': 'ok', '주의': 'w', '경고': 'e', '관망': 'g' };
  const isAI = rv => !!rv && !rv.auto && (arr(rv.obs).length > 0 || (rv.next && rv.next !== '—')) && !/데이터 축적 후 활성화/.test(String(rv.sum || ''));
  const isTpl = rv => !!rv && rv.model === 'template';
  const isLLM = rv => isAI(rv) && !isTpl(rv);
  const rvSum = (rv, k) => {
    let t = String((rv && rv.sum) || '');
    if (!isTpl(rv)) return t;
    if (!rv.tv && t && !/^총자산 변동/.test(t.trim())) return '';
    t = t.replace(/(^|[\s(])-(?=[$₩\d])/g, '$1−');
    if (S.cur === 'USD') return t.replace(/([−+]?[\d,]+(?:\.\d+)?)원\(([−+]?\$[\d,]+(?:\.\d+)?)\)/g, '$2');
    if (rv.sumKrw) return String(rv.sumKrw);
    const u = num(((S.D && S.D.usdt) || {})[k] && S.D.usdt[k].usdt) || rate();
    return t.replace(/([−+]?)([\d,]+(?:\.\d+)?)원\([−+]?\$[\d,]+(?:\.\d+)?\)/g, (a, sg, v) => sg + '₩' + v)
      .replace(/([−+]?)\$([\d,]+(?:\.\d+)?)/g, (a, sg, v) => sg + '₩' + nf('ko-KR').format(Math.round(num(v.replace(/,/g, '')) * u)));
  };
  const DOWS_MON = ['월', '화', '수', '목', '금', '토', '일'];
  const calDayV = (k, ym) => ymOf(k) === ym && S.D.realized[k] != null ? KV(num(S.D.realized[k]), S.D.hasKrw ? S.D.realizedK[k] : null) : null;
  function realDays(ym) {
    const out = [], dim = new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate(), mmP = ym.slice(5, 7) + '-';
    for (let d = 1; d <= dim; d++) { const v = calDayV(mmP + pad2(d), ym); if (v != null && Math.abs(num(v)) >= 0.005) out.push({ k: mmP + pad2(d), d, v: num(v) }); }
    return out;
  }
  function pnlTier(vals, u) {
    const q = v => Math.round(Math.abs(v) * u), P = [], N = [];
    vals.forEach(v => { v = num(v); if (v) (v > 0 ? P : N).push(q(v)); });
    P.sort((a, b) => b - a); N.sort((a, b) => b - a);
    return v => {
      v = num(v); if (!v) return 0;
      const A = v > 0 ? P : N, x = q(v), n = A.length;
      let lo = 0, hi = n;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (A[mid] > x) lo = mid + 1; else hi = mid; }
      return lo * 10 < n || !n ? 4 : lo * 10 < 4 * n ? 3 : lo * 10 < 7 * n ? 2 : 1;
    };
  }
  const tierUnit = () => (S.cur === 'USD' ? 100 : rate());
  const TIER_P = ['', '70%~100%', '40%~70%', '10%~40%', '10%'];
  const tierTxt = (v, t) => (t ? (v > 0 ? '수익 상위 ' : '손실 하위 ') + TIER_P[t] : '');
  const tierLeg = (k, scope, cl) => {
    const tip = '색 진하기 = ' + scope + '(수익·손실 따로) — 가장 진한 칸 = 수익 상위·손실 하위 ' + TIER_P[4] + ' · 그다음 ' + TIER_P[3] + ' · ' + TIER_P[2] + ' · 나머지';
    const sq = (c, t) => '<i class="' + k + ' ' + (k === 'hm' ? c : 'lv' + c) + ' lv' + t + '" title="' + tierTxt(c === 'u' ? 1 : -1, t) + '"></i>';
    return '<' + (k === 'hm' ? 'div' : 'span') + ' class="' + cl + ' pvx" title="' + tip + '" data-a="rkBrk" data-tip="' + tip + '"><span>손실</span>' + [4, 3, 2, 1].map(t => sq('d', t)).join('')
      + '<b class="hsep" aria-hidden="true">·</b>' + [1, 2, 3, 4].map(t => sq('u', t)).join('') + '<span>수익</span></' + (k === 'hm' ? 'div' : 'span') + '>';
  };
  const isoAdd =(iso, n) => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); };
  const wkRvOk = rv => !!rv && !!(rv.sum || rv.note);
  const wkClamp = (mon, ym) => { const a = ym + '-01', b = ym + '-' + pad2(new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate()), e = isoAdd(mon, 6); return [mon > a ? mon : a, e < b ? e : b]; };
  const wkSegKey = (mon, f, t) => { const wk = isoWeekKey(mon), x = mon < f || isoAdd(mon, 6) > t; return x ? wk + (f === mon ? 'a' : 'b') : wk; };
  const wkRvFor = (mon, f, t) => {
    const D = S.D, sk = wkSegKey(mon, f, t), a = D.revWk[sk];
    if (a && !a.superseded) return { rv: a, sk, seg: String(a.from || f) === f && String(a.to || t) === t, legacy: false };
    const b = sk !== isoWeekKey(mon) ? D.revWk[isoWeekKey(mon)] : null;
    return b && !b.superseded ? { rv: b, sk, seg: false, legacy: true } : { rv: null, sk, seg: false, legacy: false };
  };
  const wkStaleTxt = rv => /실현/.test(String(rv.staleWhy || '')) ? '리뷰 후 실현이 바뀌었어요 · 다시 만들기 대기' : '리뷰 방식이 바뀌었어요 · 다시 만들기 대기';
  const wkSelNow = () => { const w = S.wkSel; return w && w.day === (S.day || S.D.todayKey) ? w : null; };
  const wkOff = () => { S.wkSel = null; S.wkMore = null; };
  const MATT_K = ['mk', 'rz', 'rzf', 'fo', 'lpf', 'fl', 'fx', 'un', 'op', 'tr', 'oth'];
  function monthAtt(ym) {
    const D = S.D, dim = new Date(+ym.slice(0, 4), +ym.slice(5), 0).getDate(), mmP = ym.slice(5, 7) + '-', tISO = isoDay(D.todayKey) || todayISO();
    const o = { n: 0, days: 0, delta: 0, v2: 0, v1: 0, ap: 0 };
    MATT_K.forEach(x => { o[x] = 0; });
    for (let d = 1; d <= dim; d++) {
      if (ym + '-' + pad2(d) > tISO) break;
      o.days++;
      const k = mmP + pad2(d);
      if (ymOf(k) !== ym || !D.dayMap.has(k)) continue;
      const a = attOf(k);
      if (!a) continue;
      o.n++; o.delta += a.delta;
      if (a.v2) o.v2++; else o.v1++;
      if (a.ap) o.ap++;
      MATT_K.forEach(x => { o[x] += num(a[x]); });
    }
    return o;
  }
  function monthRealBy(ym) {
    const D = S.D, by = new Map(), inM = k => isoDay(k).slice(0, 7) === ym;
    const add = (key, sym, kind, v, vk) => { let e = by.get(key); if (!e) by.set(key, e = { sym, kind, v: 0, vk: 0, kOk: true }); e.v += v; if (vk == null) e.kOk = false; else e.vk += vk; };
    D.merged.concat(D.lpCycles).forEach(p => {
      const mp = p.realizedByDay || {}, mk = p.realizedKrwByDay || null;
      let v = 0, vk = mk ? 0 : null, any = false;
      Object.keys(mp).forEach(k => { if (!inM(k)) return; any = true; v += num(mp[k]); if (vk != null) vk = mk[k] == null ? null : vk + num(mk[k]); });
      if (!any) return;
      if (p._lp) { const pool = String(p.sym).replace(/\s*\/\s*/g, '/'); add('lp|' + pool + '|' + (p.chain || ''), pool + ' LP', 'lp', v, vk); return; }
      const sy = String(p.sym || '?');
      add((p.kind === 'gas' || p.kind === 'stake' ? p.kind + '|' : 'c|') + sy.toUpperCase(), sy, p.kind === 'gas' || p.kind === 'stake' ? p.kind : 'coin', v, vk);
    });
    const fu = D.fut.realizedByDate || {}, fk = D.fut.realizedKrwByDate || null;
    Object.keys(fu).forEach(k => { if (inM(k)) add('fut', '선물 정산', 'fut', num(fu[k]), fk ? (fk[k] == null ? null : num(fk[k])) : null); });
    const items = [];
    by.forEach(e => { const d = KV(e.v, e.kOk ? e.vk : null); if (Math.abs(d) >= 1e-9) items.push({ sym: e.sym, kind: e.kind, d }); });
    const tot = monthRealized(ym);
    return { items, tot, res: tot - sum(items, x => x.d) };
  }
  function mgBar(lbl, v, mx, dv) {
    const w = Math.abs(v) / mx * 50;
    const inner = '<span class="al">' + lbl + '</span><span class="atrk" aria-hidden="true"><i class="' + (v >= 0 ? 'p' : 'n') + '" style="left:' + (v >= 0 ? 50 : 50 - w).toFixed(2) + '%;width:' + Math.max(w, Math.abs(v) >= 0.005 ? 0.6 : 0).toFixed(2) + '%"></i><b></b></span><span class="av num ' + clsV(v) + '">' + m(v, { sign: true, compact: true });
    if (dv) return '<button type="button" class="abr abtn" data-a="attdOpen" data-v="' + esc(dv) + '" aria-haspopup="dialog" aria-label="' + esc(lbl + ' ' + m(v, { sign: true, compact: true }) + ' — 누르면 무엇 때문인지') + '">' + inner + IC.right.replace('<svg', '<svg class="acv" aria-hidden="true"') + '</span></button>';
    return '<div class="abr" role="listitem">' + inner + '</span></div>';
  }
  function monthBarRows(o) {
    const big = Math.max(Math.abs(o.mk), Math.abs(o.rz), Math.abs(o.rzf), Math.abs(o.fl), 1e-9);
    const sig = v => Math.abs(v) >= Math.max(1, 0.01 * big);
    const rows = [['시세 변동', o.mk, 'mk']], fold = [];
    let rest = o.oth;
    if (o.v2) rows.push(['현물 실현', o.rz, 'rz'], ['선물 실현', o.rzf, 'rzf']); else { rest += o.rz + o.rzf; if (o.rz) fold.push('rz'); if (o.rzf) fold.push('rzf'); }
    rows.push(['입출금', o.fl, 'fl']);
    [['tr', '매매'], ['fx', '환율'], ['fo', '선물 미반영'], ['un', '원가 미확인'], ['op', '기초 잔고 정정']].forEach(p => { if (sig(o[p[0]]) && (p[0] !== 'tr' || o.v1)) rows.push([p[1], o[p[0]], p[0]]); else { rest += o[p[0]]; if (o[p[0]]) fold.push(p[0]); } });
    if (!isZ(rest)) rows.push(['나머지', rest, 'oth', fold]);
    return rows;
  }
  function monthGlanceHTML(ym) {
    const D = S.D;
    if (!D || !D.dayMap) return '';
    const mo = +ym.slice(5), o = monthAtt(ym), rb = monthRealBy(ym);
    let att;
    if (o.n) {
      const br = monthBarRows(o), mx = Math.max.apply(null, br.map(x => Math.abs(num(x[1]))).concat([1e-9]));
      att = '<div class="attx abars mgbars abtns" role="group" aria-label="자산 변동 분해 — 줄을 누르면 무엇 때문인지">' + br.map(x => mgBar(x[0], num(x[1]), mx, 'm|' + ym + '|' + x[2])).join('') + '</div>'
        + '<div class="cap mgcap" title="' + esc((o.n < o.days ? o.days + '일 중 — 최근 30일만 분해 기록이 있어요 · ' : '') + (o.ap ? '≈ 근사 날 ' + o.ap + '일 포함 · ' : '') + '시세 변동은 날마다의 \'시세\' 줄을 더한 값 — 날짜 칸을 누르면 그날 코인별 내역') + '">'
        + (o.n < o.days ? '<b class="mgpart">분해 있는 날 ' + o.n + '일 기준</b> · 합 = 그 ' + o.n + '일의 총자산 변화 ' : '합 = ' + mo + '월 총자산 변화 ') + m(o.delta, { sign: true, compact: true }) + (o.ap ? ' <span class="pvx">· ≈ 근사 ' + o.ap + '일</span>' : '') + '</div>';
    } else att = '<div class="cap mgcap">이 달은 자산 변동 분해 기록이 없어요 — 최근 30일만 날마다 분해해요</div>';
    const resK = Math.abs(rb.res) * (S.cur === 'USD' ? 1384 : rate()), resBig = resK >= 1000 || (resK >= 100 && Math.abs(rb.res) >= Math.abs(rb.tot) * 0.01);
    const rbIt = resBig ? rb.items.concat([{ sym: '코인별로 나누지 못한 실현', kind: 'res', d: rb.res }]) : rb.items;
    const win = rbIt.filter(x => x.d > 0).sort((a, b) => b.d - a.d).slice(0, 5), lose = rbIt.filter(x => x.d < 0).sort((a, b) => a.d - b.d).slice(0, 5);
    const li = (xs, neg) => xs.length ? xs.map(x => '<div class="mgr"><span class="ell">' + esc(x.sym) + '</span><b class="num ' + clsV(x.d) + '">' + m(x.d, { sign: true, compact: true }) + '</b></div>').join('')
      : '<div class="cap mgnone">' + (neg ? '실현 손실 난 코인 없음' : '실현 수익 난 코인 없음') + '</div>';
    const resV = Math.abs(rb.res) * (S.cur === 'USD' ? 1 : rate()) >= (S.cur === 'USD' ? 0.005 : 0.5);
    const rcap = rb.items.length ? '<div class="cap mgcap" title="코인·LP 풀·가스·스테이킹·선물별 ' + mo + '월 실현을 전부 더한 값">' + mo + '월 실현 <span class="pvx">' + rb.items.length + '개</span> 합 = 달력 월 실현 ' + m(rb.tot, { sign: true, compact: true })
      + (resV ? (resBig ? ' (코인별로 나누지 못한 실현 ' : ' (날짜별 반올림 끝전 ') + m(rb.res, { sign: true }) + ' 포함)' : '') + '</div>' : '';
    const sumL = [o.n ? '시세 ' + mN(o.mk, { sign: true, compact: true }) : '', '실현 ' + mN(rb.tot, { sign: true, compact: true }), win[0] ? '상위 ' + esc(win[0].sym) + ' ' + mN(win[0].d, { sign: true, compact: true }) : ''].filter(Boolean).join(' · ');
    return '<section class="card mglance" aria-label="' + mo + '월 한눈에">' + uiFold('mglance', { cls: 'plain mgf', def: true, head: '<span class="mgt"><b class="h2">' + mo + '월 한눈에</b><span class="cap num">' + sumL + '</span></span>',
      body: () => '<div class="mgb"><div class="cap mgsub">달력에서 고른 달 · 총자산이 왜 변했는지와 코인별 실현</div><div class="mgs pvx">자산 변동 분해</div>' + att
        + '<div class="mlists"><div><div class="mgs pvx">실현 상위 5</div>' + li(win, false) + '</div><div><div class="mgs pvx">실현 하위 5</div>' + li(lose, true) + '</div></div>' + rcap + '</div>' }) + '</section>';
  }
  function vDaily() {
    const D = S.D;
    const ym = S.calYM || ymShift(0), y = +ym.slice(0, 4), mo = +ym.slice(5) - 1;
    const first = (new Date(y, mo, 1).getDay() + 6) % 7, dim = new Date(y, mo + 1, 0).getDate();
    const tISO = isoDay(D.todayKey) || todayISO();
    const mmP = pad2(mo + 1) + '-';
    let closed = 0;
    const mob = S.mobile, dotMax = mob ? 1 : 3;
    const wsel0 = wkSelNow(), wsel = wsel0 && (!wsel0.f || wsel0.f.slice(0, 7) === ym) ? wsel0 : null;
    let cells = DOWS_MON.map((d, i) => '<div class="dw' + (i === 6 ? ' sun' : i === 5 ? ' sat' : '') + '">' + d + '</div>').join('') + '<div class="dw wkc">주간 실현</div>';
    const mdays = realDays(ym);
    const mTier = pnlTier(mdays.map(x => x.v), tierUnit());
    const nRow = Math.ceil((first + dim) / 7);
    for (let r = 0; r < nRow; r++) {
      let wSum = 0, wAny = false, dFrom = 0, dTo = 0;
      for (let c = 0; c < 7; c++) {
        const d = r * 7 + c - first + 1;
        if (d < 1 || d > dim) { cells += '<div class="d e"></div>'; continue; }
        if (!dFrom) dFrom = d; dTo = d;
        const k = mmP + pad2(d), iso = ym + '-' + pad2(d), wd = (c + 1) % 7;
        const v = calDayV(k, ym);
        const has = v != null && Math.abs(num(v)) >= 0.005;
        if (has) { wSum += num(v); wAny = true; }
        if (D.dayMap.has(k) && iso < tISO) closed++;
        const fut = iso > tISO;
        const dotOn = isLLM(D.reviews[k]);
        const cn = !fut && D.dayActs ? dayCnt(k, true) : null, ns = cn ? cn.s : 0;
        const dots = ns > 0 ? '<span class="sdots num" aria-hidden="true">' + (ns > dotMax ? (mob ? '<b></b><b></b>' : '<b></b>' + ns) : '<b></b>'.repeat(ns)) + '</span>' : '';
        const at9 = !fut && D.dayMap.has(k) ? attOf(k) : null;
        const tint = has && calTint(num(v));
        const lv = tint ? mTier(num(v)) : 0;
        cells += '<button class="d' + (S.day === k ? ' sel' : '') + (iso === tISO ? ' today' : '') + (fut ? ' fut' : '') + (wd === 0 ? ' sun' : wd === 6 ? ' sat' : '') + (lv ? ' lv' + (num(v) > 0 ? 'u' : 'd') + ' lv' + lv : '') + '" data-a="pickDay" data-v="' + k + '"' + (at9 ? ' title="' + esc((mo + 1) + '월 ' + d + '일 총자산 ' + m(at9.delta, { sign: true, compact: true }) + ' — ' + attLine(at9, 3, false)) + '"' : '') + ' aria-label="' + (mo + 1) + '월 ' + d + '일' + (has ? ' 실현 ' + m(num(v), { sign: true }) : '') + (lv ? ' · 이 달 ' + tierTxt(num(v), lv) : '') + (ns ? ' · 매도 ' + ns + '건' : '') + (dotOn ? ' · AI 리뷰' : '') + '"' + (fut ? ' tabindex="-1"' : '') + '><span class="dn">' + d + (dotOn ? '<i title="AI 리뷰">AI</i>' : '') + (iso === tISO ? '<span class="tdy">오늘</span>' : '') + dots + '</span>' + (has ? '<span class="dv num ' + (tint ? cls(num(v)) : 'mut') + '">' + mcal(num(v)) + '</span>' : '') + '</button>';
      }
      const isoMon = isoAdd(ym + '-' + pad2(dFrom), -((first + dFrom - 1) % 7)), wk = isoWeekKey(isoMon);
      const isoFrom = ym + '-' + pad2(dFrom), isoTo = ym + '-' + pad2(dTo);
      const wr = wkRvFor(isoMon, isoFrom, isoTo), rv = wr.rv;
      const rng = (mo + 1) + '/' + dFrom + (dTo === dFrom ? '' : '–' + (isoTo >= tISO && isoFrom <= tISO ? '' : (mo + 1) + '/' + dTo));
      if (isoFrom > tISO) { cells += '<div class="w fut" aria-hidden="true"><span class="wr num">' + esc(rng) + '</span></div>'; continue; }
      const cur = isoTo >= tISO, ok = wkRvOk(rv), on = !!(wsel && wsel.wk === wk && (!wsel.f || wsel.f === isoFrom));
      const wkX = wr.legacy, rvTip = '주간 AI 리뷰 등급' + (wkX ? ' — ' + isoMon.slice(5).replace('-', '/') + '~' + isoAdd(isoMon, 6).slice(5).replace('-', '/') + ' 주 기준' : '') + (ok && rv.stale ? ' · ' + wkStaleTxt(rv) : '');
      const foot = ok ? '<span class="wf" title="' + esc(rvTip) + '"><span class="pill ' + (SENT[rv.s] || 'g') + ' sm">리뷰 ' + esc(rv.s || '관망') + '</span><span class="wl">›</span></span>'
        : '<span class="wf mut">' + (cur ? '진행 중' : '리뷰 없음') + '</span>';
      cells += '<button class="w' + (cur ? ' cur' : '') + (on ? ' sel' : '') + '" data-a="wkPick" data-v="' + esc(wk) + '" data-k="' + esc(wr.sk) + '" data-d="' + isoMon + '" data-f="' + isoFrom + '" data-t="' + isoTo + '" data-rv="' + (ok ? 1 : 0) + '" aria-pressed="' + on + '" aria-label="' + esc(rng) + ' 주간 실현 ' + esc(m(wSum, { sign: true })) + (ok ? ' · 주간 AI 리뷰 ' + esc(rv.s || '') + (wkX ? '(' + esc(rvTip.replace('주간 AI 리뷰 등급 — ', '')) + ')' : '') : cur ? ' · 진행 중' : ' · 리뷰 없음') + '">'
        + '<span class="wr num">' + esc(rng) + '</span><span class="wv num ' + (wAny ? cls(wSum) : 'mut') + '">' + m(wSum, { sign: true, compact: true }) + '</span>' + foot + '</button>';
    }
    const mSum = monthRealized(ym);
    const canPrev = ym > rollMinISO().slice(0, 7), canNext = ym < ymShift(0);
    const win = mdays.filter(x => x.v > 0), lose = mdays.filter(x => x.v < 0);
    const best = win.slice().sort((a, b) => b.v - a.v)[0], worst = lose.slice().sort((a, b) => a.v - b.v)[0];
    const md2 = x => (mo + 1) + '/' + x.d;
    const chips = mdays.length ? '<div class="calchips"><span class="cchip num pvx" title="날 단위 — 그날 실현(현물+선물)이 + 인 날 / − 인 날. 매매일지의 승률(청산 사이클 단위)과 다른 셈이에요">실현 있는 날 ' + mdays.length + '일 · <b class="up">수익 ' + win.length + '</b> · <b class="down">손실 ' + lose.length + '</b>' + (win.length + lose.length ? ' · 날 승률 ' + Math.round(win.length / (win.length + lose.length) * 100) + '%' : '') + '</span>'
      + (best || worst ? '<span class="cpair">' : '') + (best ? '<button class="cchip pos num" data-a="pickDay" data-v="' + best.k + '">최고의 날 <b class="up">' + md2(best) + ' ' + m(best.v, { sign: true, compact: true }) + '</b> ›</button>' : '')
      + (worst ? '<button class="cchip neg num" data-a="pickDay" data-v="' + worst.k + '">최악의 날 <b class="down">' + md2(worst) + ' ' + m(worst.v, { sign: true, compact: true }) + '</b> ›</button>' : '') + (best || worst ? '</span>' : '') + '</div>' : '';
    const listV = calView() === 'list';
    const vSeg = '<div class="seg cvseg" role="group" aria-label="보기"><button data-a="calView" data-v="cal" class="' + (listV ? '' : 'on') + '" aria-pressed="' + !listV + '">달력</button><button data-a="calView" data-v="list" class="' + (listV ? 'on' : '') + '" aria-pressed="' + listV + '">30일 목록</button></div>';
    if (listV) {
      const calL = '<div class="card cal calist"><div class="row"><h2 class="h2">최근 ' + D.daily.length + '일 마감</h2><div class="sp"></div>' + vSeg + '</div><div class="cap" style="margin-top:6px">USDT 종가·김프 포함 · 행을 누르면 그날로</div>' + recentHTML(true) + '</div>';
      return dailyLayout(calL, monthGlanceHTML(ym));
    }
    const cal = '<div class="card cal"><div class="row calhd"><h2 class="h2">' + y + '년 ' + (mo + 1) + '월</h2><div class="sp"></div>' + vSeg + '<div class="seg"><button data-a="calMonth" data-v="-1"' + (canPrev ? '' : ' disabled') + ' aria-label="이전 달">' + IC.left.replace('<svg', '<svg width="16" height="16"') + '</button><button data-a="calToday" class="on">오늘</button><button data-a="calMonth" data-v="1"' + (canNext ? '' : ' disabled') + ' aria-label="다음 달">' + IC.right.replace('<svg', '<svg width="16" height="16"') + '</button></div></div>'
      + '<div class="row" style="margin-top:10px;gap:14px;flex-wrap:wrap"><span class="cap">월 실현</span><b class="num ' + cls(mSum) + '">' + m(mSum, { sign: true }) + '</b><span class="cap">' + (ym === ymShift(0) ? '마감 ' + closed + '일 · 오늘은 23:59 마감' : '마감 기록 ' + closed + '일') + '</span></div>'
      + chips
      + '<div class="wk">' + cells + '</div><div class="cap calleg">칸 색 = 그날 실현손익(현물+선물) ' + tierLeg('lvs', '이 달 안에서 순위', 'calhl') + ' · <b class="num">·</b> = <span class="pvx">' + (S.cur === 'USD' ? '$' + CAL_DOT_USD + ' 미만' : '1만 원 미만') + '</span> · <span class="sdots"><b></b></span> = 매도 1건' + (mob ? ' · <span class="sdots"><b></b><b></b></span> = 2건 이상' : '(5건 이상은 숫자)') + ' · ' + (mob ? '<i class="aidot" aria-hidden="true"></i>' : '<span class="tag-ai">AI</span>') + ' = AI 리뷰 · 주간 칸 → 주간 리뷰</div>'
      + '</div>';
    return dailyLayout(cal, monthGlanceHTML(ym));
  }
  const calView = () => (LS.get('tj_v2_dcal') === 'list' ? 'list' : 'cal');
  function heatData() {
    const D = S.D, endIso = isoDay(D.todayKey) || todayISO(), minIso = rollMinISO();
    const end = new Date(endIso + 'T00:00:00'), start = new Date(end); start.setDate(start.getDate() - 7 * 52 - ((end.getDay() + 6) % 7));
    const days = [];
    for (const d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const iso = d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
      const v = iso >= minIso ? calDayV(iso.slice(5), iso.slice(0, 7)) : null;
      days.push({ iso, wd: (d.getDay() + 6) % 7, v: v != null && Math.abs(num(v)) >= 0.005 ? num(v) : null, out: iso < minIso });
    }
    return days;
  }
  function heatHTML() {
    const D = S.D; if (!D) return '';
    const days = heatData(), tr = days.filter(x => x.v != null);
    if (!tr.length) return '';
    const tierOf = pnlTier(tr.map(x => x.v), tierUnit());
    const w = tr.filter(x => x.v > 0).length, l = tr.length - w;
    let run = 0, r0 = null, best = { n: 0, a: null, b: null };
    tr.forEach(x => { if (x.v > 0) { if (!run) r0 = x.iso; run++; if (run > best.n) best = { n: run, a: r0, b: x.iso }; } else run = 0; });
    const mdTxt = iso => (+iso.slice(5, 7)) + '월 ' + (+iso.slice(8)) + '일';
    const byM = {}, byW = {};
    tr.forEach(x => { const mk = x.iso.slice(0, 7), a = byM[mk] || (byM[mk] = [0, 0]), b = byW[x.wd] || (byW[x.wd] = [0, 0]); a[0]++; b[0]++; if (x.v > 0) a[1]++; else b[1]++; });
    const bm = Object.keys(byM).filter(k => byM[k][0] >= 5).sort((a, b) => byM[b][1] / byM[b][0] - byM[a][1] / byM[a][0])[0];
    const bw = Object.keys(byW).filter(k => byW[k][0] >= 5).sort((a, b) => byW[b][1] / byW[b][0] - byW[a][1] / byW[a][0])[0];
    const WD = ['월', '화', '수', '목', '금', '토', '일'];
    let cells = '', mos = '', lastMo = 0;
    days.forEach((x, i) => {
      const col = Math.floor(i / 7) + 1, row = x.wd + 1, pos = 'grid-column:' + col + ';grid-row:' + row;
      if (row === 1 && +x.iso.slice(8) <= 7 && +x.iso.slice(5, 7) !== lastMo) { lastMo = +x.iso.slice(5, 7); mos += '<span style="grid-column:' + col + '">' + lastMo + '월</span>'; }
      if (x.v == null) { cells += '<span class="hm' + (x.out ? ' out' : '') + '" style="' + pos + '"></span>'; return; }
      const t = tierOf(x.v), lab = mdTxt(x.iso) + ' (' + WD[x.wd] + ') 실현 ' + m(x.v, { sign: true, compact: true }) + ' · 1년 중 ' + tierTxt(x.v, t);
      cells += '<button type="button" class="hm ' + (x.v > 0 ? 'u' : 'd') + ' lv' + t + '" style="' + pos + '" data-a="pickDay" data-v="' + x.iso.slice(5) + '" title="' + esc(lab) + '" aria-label="' + esc(lab) + '"></button>';
    });
    const stat = (k, v, sub, cl) => '<div class="hst"><span class="k">' + k + '</span><b class="v num' + (cl ? ' ' + cl : '') + '">' + v + '</b>' + (sub ? '<span class="s">' + sub + '</span>' : '') + '</div>';
    const stats = '<div class="hsts pvx">' + stat('수익 난 날', w + '일 <small>/ 매매 ' + tr.length + '일</small>', '')
      + stat('가장 길게 이긴 흐름', best.n ? best.n + '일 연속' : '—', best.n ? mdTxt(best.a) + ' ~ ' + mdTxt(best.b) : '', 'up')
      + stat('가장 좋았던 달', bm ? (+bm.slice(5)) + '월' : '—', bm ? '수익 난 날 ' + Math.round(byM[bm][1] / byM[bm][0] * 100) + '%' : '매매 5일 이상인 달 없음')
      + stat('조심할 요일', bw ? WD[bw] + '요일' : '—', bw ? '손실일 비율 ' + Math.round(byW[bw][1] / byW[bw][0] * 100) + '%' : '', bw ? 'down' : '') + '</div>';
    const leg = tierLeg('hm', '지난 1년 전체 날 중 순위', 'hleg');
    const grid = '<div class="hmw" data-ks="heat"><div class="hmm pvx">' + mos + '</div><div class="hmb"><div class="hmd pvx"><span>월</span><span></span><span>수</span><span></span><span>금</span><span></span><span>일</span></div><div class="hmg">' + cells + '</div></div></div>';
    const sumLine = '<span class="cap pvx num">수익 ' + w + '일 · 손실 ' + l + '일' + (best.n > 1 ? ' · 최장 연속 ' + best.n + '일' : '') + '</span>';
    return '<section class="card heat" aria-label="지난 1년 하루 실현손익"><div class="hmh"><div><div class="cap">지난 1년 · 하루 실현손익</div><div class="hmt">좋았던 날과 아쉬웠던 날</div></div><span class="sp"></span>' + leg + '</div>'
      + grid + (S.mobile ? uiFold('heat:st', { cls: 'plain', head: sumLine, body: () => stats, label: '1년 요약 4칸', def: false }) : stats)
      + '<div class="cap hcap">칸을 누르면 그날 카드(실현·리뷰·기록)로 · 금액은 칸 툴팁에만</div></section>';
  }
  function dailyLayout(cal, glance) {
    const wsel0 = wkSelNow(), ym = S.calYM || ymShift(0), wsel = wsel0 && (!wsel0.f || wsel0.f.slice(0, 7) === ym) ? wsel0 : null;
    const day = wsel ? wkPanelHTML(wsel) : reviewHTML();
    const heat = heatHTML();
    if (S.mobile) return heat + '<div class="dgrid dm">' + cal + day + dayEventsHTML() + glance + '</div>';
    return heat + '<div class="dgrid' + (calView() === 'list' ? ' dlist' : '') + '"><div class="dcol">' + cal + glance + '</div>' + day + '</div>' + dayEventsHTML();
  }
  function wkPanelHTML(sel) {
    const D = S.D, wk = sel.wk;
    const wkE = isoAdd(sel.from, 6), f = sel.f || sel.from, t = sel.t || wkE;
    const wr = wkRvFor(sel.from, f, t), rv = wr.rv, ok = wkRvOk(rv), mk = wr.sk, open = S.wkMore === mk, cross = wr.legacy;
    const isos = []; for (let iso = f; iso <= t; iso = isoAdd(iso, 1)) isos.push(iso);
    let tot = 0, nW = 0, nL = 0;
    isos.forEach(iso => { const k = iso.slice(5), v = calDayV(k, iso.slice(0, 7)); if (v == null || Math.abs(num(v)) < 0.005) return; tot += num(v); if (v > 0) nW++; else nL++; });
    const tISO = isoDay(D.todayKey) || todayISO(), cur = t >= tISO, curW = wkE >= tISO;
    const mdS = iso => iso.slice(5).replace('-', '/'), mdN = iso => +iso.slice(5, 7) + '/' + +iso.slice(8, 10);
    const rng = mdS(f) + ' ~ ' + mdS(t);
    const wRng = ok && rv.from && rv.to ? mdN(String(rv.from)) + '~' + mdN(String(rv.to)) : mdN(f) + '~' + mdN(t);
    const st = ok && !rv.stale && !cross ? (rv.stats || {}) : {};
    const tiles = [];
    if (st.cycles != null) tiles.push(['사이클', num(st.cycles) + '개', '']);
    if (st.win_rate_pct != null) tiles.push(['승률', num(st.win_rate_pct) + '%', st.wins != null ? '승 ' + num(st.wins) + ' · 패 ' + num(st.losses) + (num(st.cost_unknown) ? ' · 원가 미확인 ' + num(st.cost_unknown) : '') : '']);
    if (st.buys != null || st.sells != null) tiles.push(['매수 · 매도', nf('ko-KR').format(num(st.buys)) + ' · ' + nf('ko-KR').format(num(st.sells)) + '건', st.dep_to_sell_min_median != null ? '입금→매도 중앙 ' + num(st.dep_to_sell_min_median) + '분' : '']);
    const head = ok ? revTxt(rv.note || rv.sum) : '';
    const smT = ok && rv.note && rv.sum && !pvOn() ? revTxt(rv.sum) : '';
    const pN = ok ? arr(rv.patterns).length : 0, hasRule = ok && !!rv.rule, hasNx = ok && !!rv.next && rv.next !== '없음.' && rv.next !== '—';
    const full = ok && !pvOn() ? (pN ? '<ul>' + arr(rv.patterns).map(x => '<li>' + esc(revTxt(x)) + '</li>').join('') + '</ul>' : '')
      + (hasRule ? '<div class="nx"><b>규칙</b> · ' + esc(revTxt(rv.rule)) + '</div>' : '') + (hasNx ? '<div class="nx"><b>다음</b> · ' + esc(revTxt(rv.next)) + '</div>' : '') : '';
    const wkTog = [pN ? '패턴 ' + pN + '개' : '', hasRule ? '규칙' : '', hasNx ? '다음 액션' : ''].filter(Boolean).join(' · ');
    const monK = isos.find(iso => iso >= rollMinISO() && iso <= tISO);
    const pillH = ok ? '<span class="pill ' + (SENT[rv.s] || 'g') + ' sm" title="주간 AI 리뷰 등급' + (cross ? ' — ' + esc(wRng) + ' 주 기준' : '') + '">' + esc(rv.s || '관망') + '</span>'
      + (arr(rv.lossCoins).length ? '<span class="pill w sm lcchip" title="' + esc('이익 구간 속 큰 손실: ' + arr(rv.lossCoins).map(x => x.sym + ' ' + m(num(x.usd), { sign: true })).join(' · ')) + '">손실 코인 있음</span>' : '') : '';
    const staleH = ok && rv.stale ? '<span class="pill w sm wkstale" title="' + esc((rv.staleWhy || '리뷰 이후 바뀜') + (rv.rsNow != null && rv.fp && rv.fp.rs != null ? ' — 리뷰 때 ' + m(num(rv.fp.rs), { sign: true }) + ' → 지금 ' + m(num(rv.rsNow), { sign: true }) : '')) + '">' + esc(wkStaleTxt(rv)) + '</span>' : '';
    const aiSub = cross ? '<div class="wkaisub row gap8">' + pillH + '<b>주간 AI 리뷰</b><span class="cap num">' + esc(wRng) + ' 주 기준</span>' + staleH + '</div>' : '';
    return '<div class="card wkpanel" role="region" aria-label="주간 리뷰 ' + esc(rng) + '"><div class="row gap8">' + (cross ? '' : pillH) + '<b class="wkt" tabindex="-1">주간 리뷰</b><span class="cap num">' + esc(rng) + '</span>'
      + '<div class="sp"></div><button class="iconbtn" data-a="wkClose" aria-label="주간 리뷰 닫기 — 그날 카드로" title="닫기">' + IC.close + '</button></div>'
      + (cross || !staleH ? '' : '<div class="wkstl">' + staleH + '</div>')
      + '<div class="wksum"><span class="cap">주간 실현' + (cross ? ' · ' + (+f.slice(5, 7)) + '월 몫' : '') + (cur ? ' · 진행 중' : '') + '</span><b class="num ' + cls(tot) + '">' + m(tot, { sign: true }) + '</b>' + (nW + nL ? '<span class="cap num pvx">실현 있는 날 ' + (nW + nL) + '일 · 수익 ' + nW + ' · 손실 ' + nL + '</span>' : '') + '</div>'
      + (tiles.length ? '<div class="wktiles">' + tiles.map(t => '<div><div class="l">' + t[0] + '</div><div class="v num">' + esc(t[1]) + '</div>' + (t[2] ? '<div class="s num">' + esc(t[2]) + '</div>' : '') + '</div>').join('') + '</div>' : '')
      + aiSub
      + (ok ? '<p class="wkhl aib' + (open ? ' o' : '') + (rv.stale ? ' mut' : '') + '">' + esc(head) + '</p>'
        + (smT ? '<p class="wksm aib' + (open ? '' : ' clamp3') + (rv.stale ? ' mut' : '') + '">' + esc(smT) + '</p>' : '')
        + (full || smT ? (open && full ? '<div class="wkb aib">' + full + '</div>' : '') + '<button class="link wktog" data-a="wkMore" data-v="' + esc(mk) + '" aria-expanded="' + open + '">' + (open ? '접기' : '펼치기' + (wkTog ? ' — ' + wkTog : '')) + '</button>' : '')
        : '<div class="noai">' + IC.info.replace('<svg', '<svg width="18" height="18"') + (cur ? (t === wkE ? '이번 주 AI 주간 리뷰는 일요일 23:55 에 만들어져요' : '이 구간(' + mdN(f) + '~' + mdN(t) + ') AI 주간 리뷰는 ' + mdN(t) + ' 23:55 에 만들어져요') : t !== wkE || f !== sel.from ? mdN(f) + '~' + mdN(t) + ' 구간의 AI 주간 리뷰가 없어요' : '이 주는 AI 주간 리뷰가 없어요') + '</div>')
      + (monK ? '<div class="wkgo"><button class="link" data-a="wkDay" data-v="' + monK.slice(5) + '">이 주 일별 보기 ›</button></div>' : '') + '</div>';
  }
  function dayContrib(iso) {
    const D = S.D, rows = [];
    if (!iso) return rows;
    const pick = mp => { let v = 0; Object.keys(mp || {}).forEach(x => { if (isoDay(x) === iso) v += num(mp[x]); }); return v; };
    D.merged.concat(D.lpCycles).forEach(p => { const v = pick(p.realizedByDay); if (Math.abs(v) >= 0.005) rows.push({ sym: p._lp ? lpNm(p.sym, p._lp.key) : p.kind === 'gas' ? '가스(매매 외)' : p.sym, lp: !!p._lp, gas: p.kind === 'gas', stk: p.kind === 'stake', v, vk: p.realizedKrwByDay ? pick(p.realizedKrwByDay) : null, p }); });
    const lpBy = new Map();
    rows.filter(x => x.lp).forEach(x => { const k0 = String(x.p.sym) + '|' + (x.p.chain || ''); if (!lpBy.has(k0)) lpBy.set(k0, []); lpBy.get(k0).push(x); });
    lpBy.forEach(xs => {
      if (xs.length < 2) return;
      const g = { sym: String(xs[0].p.sym).replace(/\s*\/\s*/g, '/') + ' LP', lp: true, lpN: xs.length, v: sum(xs, x => x.v), vk: xs.every(x => x.vk != null) ? sum(xs, x => num(x.vk)) : null, ids: xs.map(x => x.sym), pool: String(xs[0].p.sym) };
      rows.splice(rows.indexOf(xs[0]), 1, g); xs.slice(1).forEach(x => rows.splice(rows.indexOf(x), 1));
    });
    const rf0 = num((D.fut.realizedByDate || {})[iso]);
    if (Math.abs(rf0) >= 0.005) rows.push({ sym: '선물 정산', fut: true, v: rf0, vk: (D.fut.realizedKrwByDate || {})[iso] != null ? num(D.fut.realizedKrwByDate[iso]) : null });
    rows.sort((x, y) => Math.abs(y.v) - Math.abs(x.v));
    return rows;
  }
  function feeRef(iso, gx) {
    if (S.D.taxGas && S.D.taxGas.on === false) return null;
    const fa = (S.D.feeAll || {})[iso];
    if (!Array.isArray(fa) || !(num(fa[0]) > 0)) return null;
    const tr = KV(num(fa[0]), fa[1] == null ? null : num(fa[1])) - Math.abs(num(gx));
    return tr >= 0.005 ? tr : null;
  }
  const rcptable = x => !x.lp && !x.fut && !x.gas && !x.stk;
  const DM_MAX = 500, DM_STABLE = new Set(['USDT', 'USDC', 'USDG', 'DAI', 'FDUSD', 'USD1', 'PYUSD', 'TUSD', 'USDE', 'KRW', 'USDS', 'USDP', 'USD', 'RLUSD', 'BUSD', 'USD0', 'USDD']);
  const DM_BAD = /[\s|<>"'`\\\u0000-\u001f\u007f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ue000-\uf8ff]/;
  const dmSym = s => { const t = String(s == null ? '' : s).trim().normalize('NFC').toUpperCase(); return t && t.length <= 40 && !DM_BAD.test(t) ? t : ''; };
  const dmCanon = syms => { const st = new Set(syms), out = new Map(); st.forEach(s0 => { const b = s0.length > 1 && s0[0] === '$' ? s0.slice(1) : s0; if (b !== s0 && st.has(b)) { out.set(s0, b); return; } const mt = b.match(/^(.*[A-Za-z])\d$/); if (mt && st.has(mt[1]) && mt[1] !== s0) out.set(s0, mt[1]); }); return out; };
  function dmGet(iso, sym) {
    if (!S.D || !S.D.dmOk || !iso || !sym) return null;
    const k = iso + '|' + sym, L = S.dm.local, l = L[k], sv = S.D.dayMemos[k] || null;
    if (l) {
      if (sv && num(sv.at) >= l.at) { delete L[k]; return sv; }
      if (!l.memo && !sv) { delete L[k]; return null; }
      return l.memo ? l : null;
    }
    return sv;
  }
  function dmCoins(k) {
    const D = S.D, iso = isoDay(k);
    if (!iso) return [];
    const evs = (dayFull(k) || D.evByDay.get(k) || []).filter(e => e && e.kind !== 'hidden' && /매수|매도/.test(String(e.k)) && !/평단/.test(String(e.k)));
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const pb = new Set(evs.filter(e => e.k === '온체인 매수' && e.tx && /지불/.test(String(e.d || ''))).map(payKey));
    const raw = new Map();
    evs.forEach(e => {
      if (e.k === '온체인 매도' && e.tx && pb.has(payKey(e))) return;
      const s0 = String(e.sym == null ? '' : e.sym).trim(); if (!s0) return;
      let x = raw.get(s0); if (!x) raw.set(s0, x = { b: 0, s: 0, usd: 0 });
      if (/매도/.test(String(e.k))) x.s++; else x.b++;
      const a = Math.abs(evNum(e.a)); if (isFinite(a)) x.usd += a;
    });
    const cm = dmCanon(Array.from(raw.keys())), by = new Map();
    raw.forEach((x, s0) => { const sy = dmSym(cm.get(s0) || s0); if (!sy || DM_STABLE.has(sy)) return;
      let y = by.get(sy); if (!y) by.set(sy, y = { sym: sy, b: 0, s: 0, usd: 0 }); y.b += x.b; y.s += x.s; y.usd += x.usd; });
    const out = Array.from(by.values()).sort((a, b) => b.usd - a.usd), pre = iso + '|';
    Object.keys(D.dayMemos || {}).concat(Object.keys(S.dm.local)).forEach(k9 => { if (k9.indexOf(pre) !== 0) return; const sy = k9.slice(pre.length); if (!by.has(sy) && dmGet(iso, sy)) { by.set(sy, null); out.push({ sym: sy, b: 0, s: 0, usd: 0, orphan: true }); } });
    return out;
  }
  const dmTxt = t => prTxt(t, 'dmt');
  function dmRow(iso, sym, ctx) {
    const k = iso + '|' + sym, cur = dmGet(iso, sym), ed = S.dm.ed === k, ro = !!S.D.dmErr;
    const lab = ctx === 'rc' ? '' : '<span class="dms">' + icon(sym, 'xs', S.D.symLogo[sym] || {}) + '<b>' + esc(sym) + '</b></span>';
    if (cur && !ed) return '<div class="dmr" data-k="' + esc(k) + '">' + lab + dmTxt(cur.memo) + (ro ? '' : '<button class="btn sm ghost" data-a="dmEd" data-k="' + esc(k) + '" aria-label="' + esc(sym) + ' 그날 매매 근거 고치기">고치기</button>') + '</div>';
    if (ro) return '';
    const v = ed && S.drafts['dm:' + k] == null && cur ? cur.memo : null;
    return '<div class="dmr ed" data-k="' + esc(k) + '">' + lab + '<div class="frm"><input class="field" data-pr="1" maxlength="' + DM_MAX + '" autocomplete="off" spellcheck="false" placeholder="' + esc(sym) + ' 그날 매매 근거" data-draft="' + esc('dm:' + k) + '" data-enter="dmSave" data-k="' + esc(k) + '" aria-label="' + esc(sym) + ' 그날 매매 근거' + (cur ? ' — 비우고 저장하면 지워요' : '') + '"' + (v != null ? ' value="' + esc(v) + '"' : '') + '>'
      + '<button class="btn sm pri" data-a="dmSave" data-k="' + esc(k) + '">저장</button>' + (ed ? '<button class="btn sm" data-a="dmCancel" data-k="' + esc(k) + '">취소</button>' : '') + '</div></div>';
  }
  function dmDayHTML(k) {
    const D = S.D, iso = isoDay(k);
    if (!D.dmOk || !iso) return '';
    const cs = dmCoins(k);
    if (dayWait(k)) { const cn = dayCnt(k); return cn && cn.b + cn.s > 0 ? '<div class="dsec dmemo" aria-hidden="true"><div class="cypl dmsr dmsk"><i class="skl"></i></div></div>' : ''; }
    if (!cs.length) return '';
    const withM = cs.filter(c => !!dmGet(iso, c.sym)), nMemo = withM.length;
    const names = cs.slice(0, 4).map(c => c.sym).join(' · ') + (cs.length > 4 ? ' 외 ' + (cs.length - 4) + '개' : '');
    const row = '<button type="button" class="cypl dmsr" data-a="dmSheet" data-v="' + esc(iso) + '" aria-haspopup="dialog"><span class="tx"><b>그날 매매 근거 · ' + cs.length + '코인' + (nMemo ? ' <span class="pill g sm num">' + nMemo + '/' + cs.length + '</span>' : '') + '</b><span class="cap ell">'
      + esc(names) + ' — ' + (D.dmErr ? '근거 메모 파일을 읽지 못해 지금은 저장할 수 없어요' : nMemo ? '눌러서 고치기·더 적기' : '비어 있음 · 눌러서 적기') + '</span></span>' + IC.right + '</button>';
    const shown = withM.slice(0, 3);
    const ro = shown.map(c => '<div class="dmr ro" data-k="' + esc(iso + '|' + c.sym) + '"><span class="dms">' + icon(c.sym, 'xs', D.symLogo[c.sym] || {}) + '<b>' + esc(c.sym) + '</b></span>' + dmTxt(dmGet(iso, c.sym).memo) + '</div>').join('')
      + (withM.length > 3 ? '<div class="cap dmrest">외 ' + (withM.length - 3) + '개 근거 — 시트에서</div>' : '');
    return '<div class="dsec dmemo">' + row + (ro ? '<div class="dmro">' + ro + '</div>' : '') + '</div>';
  }
  UI_SHEETS.dmemo = iso => {
    const D = S.D; if (!D || !isISO(iso)) return '';
    const cs = dmCoins(iso.slice(5));
    const has = c => !!dmGet(iso, c.sym) || S.dm.ed === iso + '|' + c.sym;
    const ord = cs.filter(has).concat(cs.filter(c => !has(c)));
    return '<div class="dmemo dmsh"><div class="cap" style="margin-bottom:8px">코인마다 한 줄 · AI 리뷰·차익 영수증 평가가 읽어요 · 비우고 저장하면 지워요</div>'
      + (D.dmErr ? '<div class="cap dmerr">' + IC.alert.replace('<svg', '<svg width="13" height="13"') + '근거 메모 파일을 읽지 못해 지금은 저장할 수 없어요</div>' : '')
      + (ord.length ? ord.map(c => dmRow(iso, c.sym, 'day')).join('') : '<div class="cap">그날 매수·매도한 코인이 없어요</div>') + '</div>';
  };
  function dmRcptHTML(R, d) {
    const D = S.D;
    if (!D.dmOk) return '';
    const sy = [dmSym(d.sym), dmSym(R.sym)].filter(Boolean), sym = sy.find(x => dmGet(R.iso, x)) || sy[0];
    if (!sym) return '';
    const k = R.iso + '|' + sym, cur = dmGet(R.iso, sym), ed = S.dm.ed === k;
    const body = cur || ed ? dmRow(R.iso, sym, 'rc') : D.dmErr ? '<div class="cap dmerr">근거 메모 파일을 읽지 못해 지금은 적을 수 없어요</div>'
      : '<div class="dmr"><span class="cap dmt">그날 ' + esc(sym) + ' 근거 메모가 없어요 — 적어 두면 AI 평가가 근거대로였는지 봐요</span><button class="btn sm" data-a="dmEd" data-k="' + esc(k) + '">근거 적기</button></div>';
    return '<section class="rsec rdm dmemo"><div class="row rtth"><span class="rtt">그날 매매 근거</span>' + (cur && !ed ? '<span class="sp"></span><button class="link sm" data-a="rcptDmDay" title="그날 카드의 코인별 근거 보기">그날 카드 ›</button>' : '') + '</div>' + body + '</section>';
  }
  const dmInput = k => {
    const pick = root => root ? Array.from(root.querySelectorAll('input[data-draft]')).find(x => x.getAttribute('data-draft') === 'dm:' + k) || null : null;
    return (S.drawer || S.sheet ? pick($('#overlay')) : null) || pick($('#view')) || pick(document.body);
  };
  function dmSwapKeepForm() {
    const v = $('#view'); if (!v || !S.D) return;
    v.querySelectorAll('.dmemo .dmr[data-k]').forEach(r => {
      if (r.querySelector('input')) return;
      const k = r.getAttribute('data-k') || '', c = dmGet(k.slice(0, 10), k.slice(11)), t = r.querySelector('.dmt');
      if (t && c) TJDOM.replace(t, dmTxt(c.memo));
    });
  }
  function reviewHTML() {
    const D = S.D, k = S.day || D.todayKey;
    const rv0 = D.reviews[k] || null, rv = rv0 && isYMD(rv0.iso) && String(rv0.iso).slice(0, 10) < rollMinISO() ? null : rv0, ai = isAI(rv);
    const snap = D.dayMap.get(k);
    const isToday = k === D.todayKey;
    const r = KV(num(D.realized[k]), D.hasKrw ? D.realizedK[k] : null);
    const iso = isoDay(k);
    const dt = iso ? new Date(iso + 'T00:00:00') : null;
    const label = dt ? (S.mobile ? (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일' : (dt.getMonth() + 1) + '월 ' + dt.getDate() + '일') + ' (' + DOWS[dt.getDay()] + ')' : k;
    const u = D.usdt[k] || {};
    const total = isToday ? D.total : (snap ? dayV(snap) : null);
    const prevSnap = (() => { const i = D.daily.findIndex(x => x.date === k); return i > 0 ? D.daily[i - 1] : null; })();
    const pvV = prevSnap ? dayV(prevSnap) : null;
    const delta = total != null && prevSnap ? total - pvV : null;
    const isStep = isToday ? !!D._todayStep : D.steps.indexOf(k) >= 0;
    const isSplit = isToday ? !!D._todaySplit : !!(snap && snap.split);
    const dFl = isToday ? D._todayFlow : (snap && snap.flow != null ? dayFlowV(snap) : null);
    const cn = dayCnt(k), evs = cn ? null : (D.evByDay.get(k) || []).filter(srcPass);
    const sells = cn ? cn.s : evs.filter(e => /매도/.test(e.k)).length, nRec = cn ? cn.n : evs.length;
    const nav = S.mobile
      ? '<div class="seg dnav"><button data-a="dayStep" data-v="-1" aria-label="전날">' + IC.left.replace('<svg', '<svg width="18" height="18"') + '</button><span class="dlab num">' + esc(label) + '</span><button data-a="dayStep" data-v="1" aria-label="다음 날"' + (isToday ? ' disabled' : '') + '>' + IC.right.replace('<svg', '<svg width="18" height="18"') + '</button></div>'
      : '<div class="seg"><button data-a="dayStep" data-v="-1" aria-label="전날">' + IC.left.replace('<svg', '<svg width="16" height="16"') + '</button><button data-a="dayStep" data-v="1" aria-label="다음날"' + (isToday ? ' disabled' : '') + '>' + IC.right.replace('<svg', '<svg width="16" height="16"') + '</button></div>';
    const lcTag = ai && arr(rv.lossCoins).length ? '<span class="pill w sm lcchip" title="' + esc('이익일 속 큰 손실: ' + arr(rv.lossCoins).map(x => x.sym + ' ' + m(num(x.usd), { sign: true })).join(' · ')) + '">손실 코인 있음</span>' : '';
    const tpl = isTpl(rv), aiLbl = tpl ? '<span class="tag-ai" title="체결 없는 날이라 AI 대신 그날 마감 숫자로 만든 요약이에요">자동 요약</span>' : '<span class="tag-ai">AI 리뷰</span>';
    const sentTag = ai ? '<span class="tag pill ' + (SENT[rv.s] || 'g') + '">' + esc(rv.s) + '</span>' + lcTag + (S.mobile ? '' : aiLbl) : '';
    const fp = ai && rv.fp && typeof rv.fp === 'object' ? rv.fp : null;
    const srvStale = ai && typeof rv.stale === 'boolean';
    const stale = srvStale ? rv.stale : (fp && iso ? (() => { const da = D.dayActs && D.dayActs[iso], cur = { rs: num((D.f.realizedByDate || {})[iso]), rf: num((D.fut.realizedByDate || {})[iso]) };
      const off = ['rs', 'rf'].some(x => { const a0 = num(fp[x]), b0 = cur[x]; return Math.abs(a0 - b0) > Math.max(1, 0.01 * Math.max(Math.abs(a0), Math.abs(b0))); });
      return off || (da && fp.n != null && num(fp.n) !== num(da.n)); })() : false);
    const why = srvStale && rv.staleWhy ? String(rv.staleWhy) : '';
    const staleTag = stale ? '<div class="stalebadge" title="리뷰를 만든 뒤 그날 기록이나 리뷰 방식이 바뀌었어요' + (why ? '(' + esc(why) + ')' : '') + '. 위 숫자가 최신이고, 리뷰는 다음 보충 때 다시 만들어져요">' + IC.info.replace('<svg', '<svg width="14" height="14"') + '<span>' + (/^리뷰 방식 변경$/.test(why) ? '리뷰 방식이 바뀌었어요' : '리뷰 이후 기록이 바뀌었어요') + (why && !/^리뷰 방식 변경$/.test(why) ? ' · ' + esc(why) : '') + ' · 다시 만들기 대기</span></div>' : '';
    const dqTag = ai && rv.dq && !pvOn() ? '<div class="dqnote aib">' + IC.alert.replace('<svg', '<svg width="14" height="14"') + '<span><b>데이터 품질</b> · ' + esc(revTxt(rv.dq)) + '</span></div>' : '';
    const rbA = mp => (mp && mp[iso] != null ? mp[iso] : mp ? mp[k] : 0);
    const rs0 = iso ? num(rbA(D.f.realizedByDate)) : 0, rf0 = iso ? num(rbA(D.fut.realizedByDate)) : 0;
    const futOnly = Math.abs(rs0) < 0.005 && Math.abs(rf0) >= 0.005;
    const cntBits = [];
    if (cn) { cntBits.push('매도 ' + sells + '건'); if (cn.pay) cntBits.push('스왑 지불 ' + cn.pay + '건'); if (cn.b) cntBits.push('매수 ' + cn.b + '건'); }
    else cntBits.push('매도 ' + sells + '건');
    cntBits.push('기록 ' + nRec + '건');
    const facts = cntBits.map((x, i) => '<span class="nowrap">' + x + (i < cntBits.length - 1 || isToday ? ' ·' : '') + '</span>').join(' ') + (isToday ? ' <span class="nowrap">지금 평가손익 ' + '<span class="' + cls(D.unreal) + '">' + mN(D.unreal, { sign: true, compact: true }) + '</span></span>' : '');
    const tiles = '<div class="dtiles num">' + (cn ? [['매도', sells], ['스왑 지불', cn.pay || 0], ['매수', cn.b || 0], ['기록', nRec]] : [['매도', sells], ['기록', nRec]]).map(x => '<div><span>' + x[0] + '</span><b>' + x[1] + '</b></div>').join('') + '</div>';
    const cRows = dayContrib(iso);
    const odd = cRows.length ? r - sum(cRows, x => KV(x.v, x.vk)) : 0, tiny = !!r && Math.abs(r) * rate() < 100;
    const contrib = (() => {
      if (!cRows.length) return '';
      const nTop = S.mobile ? 2 : 5;
      const top = cRows.slice(0, nTop), mx = Math.max.apply(null, top.map(x => Math.abs(x.v))), rest = cRows.slice(nTop);
      return '<div class="contrib"><div class="ttl">그날 실현 기여 <span class="mut">' + cRows.length + '개</span></div>' + top.map((x, i) => { const vv = KV(x.v, x.vk);
        const inner = (x.fut ? '<span class="ic xs" style="background:var(--surface3);color:var(--text2)">' + IC.scale.replace('<svg', '<svg width="12" height="12"') + '</span>' : x.gas ? '<span class="ic xs" style="background:var(--surface3);color:var(--text2)">' + IC.fuel.replace('<svg', '<svg width="12" height="12"') + '</span>' : x.lp ? '<span class="ic xs" style="background:var(--surface3);color:var(--text2)">' + IC.layers.replace('<svg', '<svg width="12" height="12"') + '</span>' : icon(x.sym, 'xs', D.symLogo[String(x.sym).toUpperCase()] || {}))
          + (x.lpN ? '<span class="ell lpn" title="' + esc(x.ids.join('\n')) + '"><span class="nm">' + esc(x.sym) + '</span> <span class="id">×' + x.lpN + '</span></span>' : lpNmHTML(x.sym, x.lp)) + '<span class="cb2"><i class="' + (vv >= 0 ? 'p' : 'n') + '" style="width:' + Math.max(3, Math.abs(x.v) / mx * 100).toFixed(1) + '%"></i></span><b class="num ' + clsV(vv) + '">' + m(vv, { sign: true, compact: true }) + '</b>';
        if (x.lp) { const lk = x.lpN ? '' : String((x.p && x.p.key) || ''), pool = String(x.lpN ? x.pool : (x.p && x.p.sym) || x.sym);
          return '<button class="cr clk" data-a="lpGo" data-v="' + esc(iso + '|' + pool + '|' + lk) + '" title="이 LP 보기 ›" aria-label="' + esc(String(x.sym) + ' — 이 LP 보기') + '">' + inner + '</button>'; }
        if (x.fut) return '<button class="cr clk" data-a="futRcpt" data-v="' + esc(iso) + '" data-rk="' + (i + 1) + '" title="선물 영수증 — 그날 선물 진입·청산">' + inner + '</button>';
        return rcptable(x) ? '<button class="cr clk" data-a="receipt" data-v="' + esc(iso + '|' + x.sym) + '" data-rk="' + (i + 1) + '" title="' + esc(x.sym) + ' 차익 영수증">' + inner + '</button>' : '<div class="cr"' + (x.gas ? ' title="' + esc('매매 외 가스(실패·승인·전송·브릿지·LP) — 매매에 든 가스·수수료는 각 코인 원가·손익에 들어 있어요') + '"' : '') + '>' + inner + '</div>'; }).join('')
        + (rest.length ? '<div class="cap num crest">외 ' + rest.length + '개' + (S.mobile ? ' · ' + esc(rest.slice(0, 3).map(x => x.lpN ? x.sym : String(x.sym).replace(/\s+#\d+$/, '')).join(' · ')) + (rest.length > 3 ? ' 등' : '') : '') + ' · ' + mN(sum(rest, x => KV(x.v, x.vk)), { sign: true, compact: true }) + '</div>' : '')
        + (Math.abs(odd) * (S.cur === 'USD' ? 1 : rate()) >= (S.cur === 'USD' ? 0.005 : 0.5) ? '<div class="cap num crest" title="코인·LP·선물별 줄에서 빠진 $0.005 미만 조각(가스·스테이블 환전 끝전 등)과 반올림의 합 — 위 줄들과 더하면 제목 실현과 같아요">' + (Math.abs(odd) * (S.cur === 'USD' ? 1 : rate()) < (S.cur === 'USD' ? 1 : 1000) ? '기타 소액 ' : '그 밖 ') + mN(odd, { sign: true }) + '</div>' : '') + '</div>';
    })();
    const kp = u.kimp != null ? num(u.kimp) : null;
    const noTrade = !isToday && !sells && !(cn && (cn.b || cn.pay)) && (!evs || !evs.some(e => /매수|매도/.test(e.k))) && (!r || tiny);
    const mk = delta != null ? (isSplit && dFl != null ? delta - dFl : isStep ? null : delta) : null;
    const attK = attOf(k);
    const noTradeTxt = '거래 없는 날' + (mk != null && !attK ? ' · 시장 변동 <b class="num ' + cls(mk) + '">' + m(mk, { sign: true, compact: true }) + '</b>' : '');
    const rvOpen = S.revOpen === k;
    const sumT = ai ? rvSum(rv, k) : '';
    const preRaw = tpl && !isToday && (!!rv.pre || (!rv.tv && num(rv.at) > 0 && iso && num(rv.at) < Date.parse(iso + 'T00:00:00+09:00') / 1000 + 86400));
    const preT = preRaw && !!snap;
    const tplNote = tpl && rv.note && String(rv.sum || '').indexOf(String(rv.note).trim()) === 0 && /총자산 변동/.test(rv.note) ? '' : (rv ? rv.note : '');
    const attA = tpl && !preRaw ? attOf(k) : null, coreT = attA ? attCore(attA) : '';
    const lead = ai ? (tpl ? [tplNote, preRaw ? '' : (coreT || sumT)].filter(Boolean).join(' ') + (preT ? ' (자산 변동은 위 줄이 마감 값 — 이 요약은 마감 뒤 다시 써요)' : '') : (rv.note || sumT || '')) : '';
    const obsN = ai ? arr(rv.obs).length : 0, hasNx = ai && rv.next && rv.next !== '—' && rv.next !== '없음.';
    const more = ai && !pvOn() && (obsN || hasNx || rv.dq || (!tpl && rv.note && rv.sum));
    const full = ai && !pvOn() ? (!tpl && rv.note && rv.sum ? '<p class="rvsum aib">' + esc(revTxt(sumT)) + '</p>' : '') + (obsN ? '<ul class="aib">' + arr(rv.obs).map(o => '<li>' + esc(revTxt(o)) + '</li>').join('') + '</ul>' : '')
      + (hasNx ? '<div class="nx aib"><b>다음 액션</b> · ' + esc(revTxt(rv.next)) + '</div>' : '') + dqTag : '';
    const togBits = [obsN ? '관찰 ' + obsN : '', hasNx ? '다음 액션' : ''].filter(Boolean).join(' · ');
    const tog = more ? '<button class="link rvtog" data-a="revTog" data-v="' + esc(k) + '" aria-expanded="' + rvOpen + '">' + (rvOpen ? '접기' : (S.mobile ? '전체' : '펼치기') + (togBits && !S.mobile ? ' · ' + togBits : '')) + (rv.dq && !rvOpen ? ' <span class="rvdq">' + IC.alert.replace('<svg', '<svg width="13" height="13"') + '데이터 품질</span>' : '') + IC.chev.replace('<svg', '<svg class="cv' + (rvOpen ? ' o' : '') + '" width="14" height="14"') + '</button>' : '';
    const aiBox = ai ? (S.mobile
      ? '<div class="rvbox' + (stale ? ' st' : '') + '"><div class="rvh">' + aiLbl + '<span class="sp"></span>' + tog + '</div>' + staleTag + '<p class="rvlead' + (tpl ? '' : ' aib') + (rvOpen || tpl ? '' : ' clamp3') + (stale ? ' mut' : '') + '">' + esc(tpl && pvOn() ? hs(lead, true) : revTxt(lead)) + '</p>' + (rvOpen ? full : '') + '</div>'
      : staleTag + '<p class="rvlead' + (tpl ? '' : ' aib') + (rvOpen || tpl ? '' : ' clamp2') + (stale ? ' mut' : '') + '">' + esc(tpl && pvOn() ? hs(lead, true) : revTxt(lead)) + '</p>' + (rvOpen ? full : '') + (tog ? '<div class="rvtogw">' + tog + '</div>' : ''))
      : '<div class="noai">' + IC.info.replace('<svg', '<svg width="18" height="18"') + (isToday ? '오늘의 AI 리뷰는 23:50 에 만들어져요' : noTrade ? noTradeTxt : '이 날은 AI 리뷰가 아직 없어요') + '</div>';
    const fx = (u.usdt ? 'USDT <span class="num">₩' + nf('ko-KR').format(num(u.usdt)) + '</span>' : '') + (kp != null ? (u.usdt ? ' · ' : '') + '김프 ' + '<span class="num">' + pctS(kp, 2) + '</span>' + kimpChip(kp) : '');
    const stPill = '<span class="pill ' + (isToday ? 'w' : 'g') + ' sm"' + (!isToday && !snap ? ' title="최근 30일 밖이라 그날 총자산 마감 기록이 없어요 — 전일 대비·자산 변동 분해도 없어요"' : '') + '>' + (isToday ? (S.mobile ? '실시간' : '실시간 · 23:59 마감') : (snap ? (S.mobile ? '마감' : '마감 기록') : '마감 기록 없음')) + '</span>';
    const dxv = (v, c9) => { const t9 = m(v, { sign: true, compact: !S.dxFull });
      return '<span class="' + c9 + ' dxv' + (S.dxFull ? ' xf" style="--n:' + plainT(t9).length : '') + '" role="button" tabindex="0" data-a="dxTog" aria-pressed="' + !!S.dxFull + '" title="' + esc(m(v, { sign: true }) + ' · 누르면 ' + (S.dxFull ? '줄인 금액' : '전체 금액')) + '">' + t9 + '</span>'; };
    const h3 = '<b class="v num">' + (tiny ? '<span class="mut">≈0</span> <small class="mut tiny">(끝전 ' + m(r, { sign: true }) + ')</small>' : r ? dxv(r, cls(r)) : '<span class="mut">없음</span>') + '</b>';
    const totS = total != null ? '<span' + (!isToday ? apTitle(snap) : '') + '>총자산 ' + (!isToday && apOf(snap) ? '≈ ' : '') + m(total, { compact: true }) + '</span>' : '';
    const chgV = delta != null ? dxv(delta, isStep || isSplit ? 'mut' : cls(delta)) : '<span class="mut">—</span>';
    const chgS = delta != null ? pctS(pvV ? delta / pvV * 100 : null, 2) + (attK ? '' : isSplit && dFl != null ? ' ' + flowSplit(delta, dFl, isToday ? D._todayFlowTop : (snap || {}).flowTop, true) : (isStep ? ' · 입출금 포함' : '')) : (snap || isToday ? '전일 마감 없음' : '');
    const tiles2 = delta == null ? '<div class="dtl2 one"><div class="dtile"><span class="l">' + (futOnly ? '선물 정산' : '총 실현') + '</span>' + h3 + '<span class="s num facts">' + facts + '</span>'
        + '<span class="s num sans dnochg">' + [totS, '전일 마감 기록 없음'].filter(Boolean).map(x => '<span class="nowrap">' + x + '</span>').join(' · ') + '</span></div></div>'
      : '<div class="dtl2"><div class="dtile"><span class="l">' + (futOnly ? '선물 정산' : '총 실현') + '</span>' + h3 + '<span class="s num facts">' + facts + '</span></div>'
      + '<div class="dtile dchg"><span class="l">전일 대비</span><b class="v num">' + chgV + '</b><span class="s num">' + [chgS, totS].filter(Boolean).map((x, i, a9) => i < a9.length - 1 ? x + ' ·' : '<span class="nowrap">' + x + '</span>').join(' ') + '</span></div></div>';
    const whyH = attK ? '<div class="dsec"><div class="dst">왜 움직였나</div>' + attBars(attK, k, false) + '</div>' : '';
    const fillsH = dayFillsHTML(k);
    if (S.mobile) {
      return '<div class="card rev m" data-anc="day:' + esc(k) + '"><div class="row gap8">' + nav + '<div class="sp"></div>' + sentTag + stPill + '</div>'
        + tiles2 + (fx ? '<div class="cap num fxl">' + fx + '</div>' : '') + whyH + krwDayHTML(iso) + fillsH + '<div class="rvq">' + aiBox + '</div>' + contrib + dmDayHTML(k) + weekRevHTML(iso) + '</div>';
    }
    return '<div class="card rev" data-anc="day:' + esc(k) + '"><div class="row gap8 dhd"><b class="dlab">' + esc(label) + '</b>' + sentTag + stPill + '<div class="sp"></div>' + nav + '</div>'
      + tiles2 + (fx ? '<div class="cap num fxl">' + fx + '</div>' : '') + whyH + krwDayHTML(iso)
      + fillsH + '<div class="rvq">' + aiBox + '</div>' + contrib + dmDayHTML(k) + weekRevHTML(iso) + '</div>';
  }
  const FB_SLOT = 30, FB_N = 1440 / FB_SLOT, FB_TIP_MAX = 12;
  function dayFillsHTML(k) {
    const D = S.D;
    const evs = (dayFull(k) || D.evByDay.get(k) || []).filter(srcPass).filter(e => /매수|매도/.test(String(e.k)) && !/평단/.test(String(e.k)));
    if (dayWait(k)) { const cn = dayCnt(k); return cn && cn.b + cn.s + cn.pay > 0 ? '<div class="dsec dfills" aria-busy="true"><div class="dst row"><span>그날 체결</span><span class="sp"></span><span class="cap" role="status">받는 중…</span></div><div class="fbars fbsk" aria-hidden="true"></div><div class="fx5 num" aria-hidden="true"><span>&nbsp;</span></div></div>' : ''; }
    if (!evs.length) return '';
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const pb = new Set(evs.filter(e => e.k === '온체인 매수' && e.tx && /지불/.test(String(e.d || ''))).map(payKey));
    const val = e => { if (S.cur !== 'USD' && e.aK != null && isFinite(e.aK)) return Math.abs(num(e.aK)) / rate(); const a = Math.abs(evNum(e.a)); return isFinite(a) ? a : 0; };
    const pts = evs.map(e => { const hm = String(e.iso || e.t || '').match(/(\d{2}):(\d{2})\s*$/); if (!hm) return null;
      const mn = +hm[1] * 60 + +hm[2]; return { e, mn, slot: Math.min(FB_N - 1, Math.floor(mn / FB_SLOT)), a: val(e), sell: /매도/.test(e.k), pay: e.k === '온체인 매도' && !!e.tx && pb.has(payKey(e)) }; }).filter(Boolean);
    if (!pts.length) return '';
    const sl = new Map();
    pts.forEach(p => { let x = sl.get(p.slot); if (!x) sl.set(p.slot, x = { s: 0, b: 0, nS: 0, nB: 0, ps: [] }); if (p.sell) { x.s += p.a; x.nS++; } else { x.b += p.a; x.nB++; } x.ps.push(p); });
    const vmax = Math.max.apply(null, Array.from(sl.values()).flatMap(x => [x.s, x.b]).concat([1e-12]));
    const nS = pts.filter(p => p.sell && !p.pay).length, nP = pts.filter(p => p.pay).length, nB = pts.length - nS - nP;
    const hh = v => v > 0 ? Math.max(2.5, 100 * Math.sqrt(v / vmax)) : 0;
    const slotLab = i => pad2(Math.floor(i * FB_SLOT / 60)) + ':' + pad2(i * FB_SLOT % 60) + '~' + pad2(Math.floor((i + 1) * FB_SLOT / 60) % 24 === 0 && i + 1 === FB_N ? 24 : Math.floor((i + 1) * FB_SLOT / 60)) + ':' + pad2((i + 1) * FB_SLOT % 60);
    const cols = Array.from(sl.entries()).sort((a, b) => a[0] - b[0]).map(([i, x]) => {
      const lab = slotLab(i), sum0 = (n, v, t) => n ? t + ' ' + n + '건 ' + m(v) : '';
      const head = [sum0(x.nS, x.s, '매도'), sum0(x.nB, x.b, '매수')].filter(Boolean).join(' · ');
      const rows = x.ps.slice().sort((a, b) => a.mn - b.mn || b.a - a.a);
      const tip = '<span class="fbtip" role="tooltip"><b class="num">' + lab + '</b><span class="fbh num">' + esc(head) + '</span>'
        + rows.slice(0, FB_TIP_MAX).map(p => '<span class="fbr num"><span class="' + (p.sell ? 'up' : 'down') + '">' + esc(String(p.e.t || '').slice(-5)) + ' ' + esc(p.pay ? '스왑 지불' : term(p.e.k)) + '</span> ' + esc(evNm(p.e)) + ' · ' + esc(evQ(p.e)) + ' · ' + String(evA(p.e)).replace(/<[^>]+>/g, '') + '</span>').join('')
        + (rows.length > FB_TIP_MAX ? '<span class="cap">외 ' + (rows.length - FB_TIP_MAX) + '건 — 그날의 기록에</span>' : '') + '</span>';
      return '<button type="button" class="fbc' + (i < FB_N / 3 ? ' l' : i >= FB_N * 2 / 3 ? ' r' : '') + '" data-a="fbTip" data-v="' + i + '" style="left:' + (i / FB_N * 100).toFixed(3) + '%" aria-label="' + esc(lab + ' ' + head) + '">'
        + (x.s > 0 ? '<i class="fbs" style="--h:' + hh(x.s).toFixed(2) + '%"></i>' : '') + (x.b > 0 ? '<i class="fbb" style="--h:' + hh(x.b).toFixed(2) + '%"></i>' : '') + tip + '</button>';
    }).join('');
    return '<div class="dsec dfills"><div class="dst row"><span>그날 체결</span><span class="sp"></span><span class="cap pvx">30분마다 금액 합 · 위 = 매도' + (nP ? '(스왑 지불 포함)' : '') + ' · 아래 = 매수 · 막대에 올리면 체결 목록</span></div>'
      + '<div class="fbars" role="group" aria-label="' + esc('그날 체결 ' + pts.length + '건 30분 막대 — 매도 ' + nS + (nP ? ' · 스왑 지불 ' + nP : '') + ' · 매수 ' + nB + ' · 칸 ' + sl.size + '개') + '"><span class="fmid" aria-hidden="true"></span>' + cols + '</div>'
      + '<div class="fx5 num pvx" aria-hidden="true"><span>00시</span><span>06시</span><span>12시</span><span>18시</span><span>24시</span></div></div>';
  }
  function isoWeekKey(iso) {
    const d = new Date(iso + 'T00:00:00Z'), wd = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - wd + 3);
    const y = d.getUTCFullYear(), jan4 = new Date(Date.UTC(y, 0, 4));
    const w = 1 + Math.round(((d - jan4) / 864e5 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
    return y + '-W' + pad2(w);
  }
  function weekRevHTML(iso) {
    if (!iso) return '';
    const wk = isoWeekKey(iso);
    const dw = (new Date(iso + 'T00:00:00').getDay() + 6) % 7, mon = isoAdd(iso, -dw);
    const fx = wkClamp(mon, iso.slice(0, 7));
    const rv = wkRvFor(mon, fx[0], fx[1]).rv;
    if (!rv || !(rv.sum || rv.note)) return '';
    const tISO = isoDay(S.D.todayKey) || todayISO(), cur = fx[0] <= tISO && tISO <= fx[1];
    return '<div class="wkrev wkln"><button class="link" data-a="wkPick" data-v="' + esc(wk) + '" data-d="' + mon + '" data-f="' + fx[0] + '" data-t="' + fx[1] + '" aria-label="' + esc((cur ? '이번 주' : '그 주') + ' 주간 리뷰 열기') + '">'
      + '<span class="tag pill ' + (SENT[rv.s] || 'g') + ' sm">' + esc(rv.s || '관망') + '</span>' + (cur ? '이번 주' : '그 주') + ' 리뷰 ›'
      + (rv.stale ? ' <span class="pill w sm" title="' + esc(rv.staleWhy || '리뷰 이후 바뀜') + '">' + esc(wkStaleTxt(rv)) + '</span>' : '') + '</button></div>';
  }
  const evNum = s0 => { const t = String(s0 == null ? '' : s0).replace(/[,\s]/g, ''); const mm = t.match(/^[+\-−]?\$?([\d.]+)/); return mm ? parseFloat(mm[1]) * (/^[\-−]/.test(t) ? -1 : 1) : NaN; };
  function groupDayEvs(evs) {
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const buys = new Map();
    evs.forEach(e => { if (e.k === '온체인 매수' && e.tx && /지불/.test(String(e.d || ''))) buys.set(payKey(e), e); });
    const pays = new Map();
    const rest = evs.filter(e => { if (e.k === '온체인 매도' && e.tx && buys.has(payKey(e))) { const b = buys.get(payKey(e)); (pays.get(b) || pays.set(b, []).get(b)).push(e); return false; } return true; });
    const items = [], byK = new Map();
    rest.forEach(e => {
      const gk = (e.src || '') + '|' + String(e.t || '') + '|' + String(e.sym || '') + '|' + e.k;
      let it = byK.get(gk);
      if (!it) { it = { gk, evs: [] }; byK.set(gk, it); items.push(it); }
      it.evs.push(e);
    });
    const out = [];
    items.forEach(it => {
      const min = /거래소/.test(it.evs[0].k) ? 2 : 3;
      if (it.evs.length >= min) {
        const qs = it.evs.map(e => evNum(e.q)), as = it.evs.map(e => evNum(e.a));
        out.push({ grp: it.evs, gk: it.gk, e: it.evs[0], q: qs.every(isFinite) ? sum(qs) : null, a: as.every(isFinite) && /\$/.test(String(it.evs[0].a || '')) ? sum(as) : null, aK: evAK(it.evs),
          n: it.evs.length + sum(it.evs, e => (pays.get(e) || []).length) });
      } else it.evs.forEach(e => out.push({ e, pay: pays.get(e) || null, n: 1 + (pays.get(e) || []).length }));
    });
    return out;
  }
  function payChip(ps) {
    if (!ps || !ps.length) return '';
    const by = Object.create(null), bl = Object.create(null); ps.forEach(x => { const k0 = String(x.sym || '?'); by[k0] = (by[k0] || 0) + (isFinite(evNum(x.a)) ? evNum(x.a) : 0); (bl[k0] || (bl[k0] = [])).push(x); });
    return ' <span class="paychip" title="스왑 지불 레그 — 매수 대금으로 함께 나간 코인(원장에선 그 코인 매도로 기록)">지불 ' + Object.keys(by).map(k0 => esc(k0) + (by[k0] ? ' ' + m(KV(by[k0], evAK(bl[k0]))) : '')).join(' · ') + '</span>';
  }
  function futMerge(items, fl, iso) {
    if (!arr(fl).length) return items;
    const hm = t => (iso && /^\d\d:\d\d$/.test(t) ? Date.parse(iso + 'T' + t + ':00+09:00') / 1000 : NaN);
    const fTs = x => (num(x.ts) > 0 ? num(x.ts) : isFinite(hm(String(x.t || ''))) ? hm(String(x.t)) + 59 : Infinity);
    const eTs = e => (num(e.ts) > 0 ? num(e.ts) : hm(String(e.t || '').slice(-5)));
    const key = it => (it.fut ? fTs(it.fut) : eTs(it.e || {}));
    const out = items.slice();
    arr(fl).slice().sort((a, b) => fTs(b) - fTs(a)).forEach(x => {
      const t = fTs(x), i = out.findIndex(it => key(it) < t);
      const it = { fut: x, n: 0, gk: 'fut|' + (x.exKey || '') };
      if (i < 0) out.push(it); else out.splice(i, 0, it);
    });
    return out;
  }
  function dayRowsHTML(items) {
    const cell = (e, extra) => '<td class="l mut num nowrap">' + esc(String(e.t).slice(6)) + '</td><td class="l">' + evPill(e.k) + '</td><td class="l"><b>' + esc(evNm(e)) + '</b>' + impChip(e) + '</td>' + extra;
    const txc = e => '<td class="tx num nowrap">' + (e.tx && e.tx !== '—' ? '<button data-a="copy" data-v="' + esc(e.tx) + '" title="복사 · ' + esc(e.tx) + '">' + esc(short(e.tx)) + '</button>' : '—') + '</td>';
    if (S.mobile || S.narrow) return '<div style="padding:4px 16px">' + items.map(it => {
      if (it.fut) return futDayHTML(it.fut, 'div');
      const e = it.e, g = it.grp, open = g && S.dayGrpOpen && S.dayGrpOpen.has(it.gk);
      const head = '<div data-n="' + it.n + '" style="padding:11px 0;border-bottom:1px solid var(--line);font-size:14px"><div class="row gap8">' + evPill(e.k) + '<b>' + esc(evNm(e)) + '</b>' + impChip(e) + (g ? ' <button class="link gtog" data-a="dayGrp" data-v="' + esc(it.gk) + '" aria-expanded="' + !!open + '">' + g.length + '건 체결 ' + (open ? '접기' : '펼치기') + '</button>' : '') + '<span class="sp"></span><span class="mut num" style="font-size:12.5px">' + esc(String(e.t).slice(6)) + '</span></div>'
        + '<div class="t2" style="margin-top:3px;font-size:13.5px">' + evDH(e) + (it.pay ? payChip(it.pay) : '') + '</div><div class="row sub num"><span>' + (g ? (it.q != null ? (evXf(e) ? pvW(PVM.q) : q(it.q)) : '—') : esc(evQ(e))) + '</span><span class="sp"></span><span>' + (g ? (it.a != null ? (evXf(e) ? esc(pvMoney('', false)) : m(KV(it.a, it.aK))) : '—') : evA(e)) + '</span></div></div>';
      return head + (open ? g.map(x => '<div data-n="0" style="padding:7px 0 7px 14px;border-bottom:1px dashed var(--line);font-size:13px" class="row sub num"><span>' + esc(evQ(x)) + '</span><span class="sp"></span><span>' + evA(x) + '</span></div>').join('') : '');
    }).join('') + '</div>';
    return '<div style="overflow-x:auto"><table class="ev" style="margin:0 24px;width:calc(100% - 48px)"><thead><tr><th scope="col" class="l">시각</th><th scope="col" class="l">종류</th><th scope="col" class="l">자산</th><th scope="col" class="l">내용</th><th scope="col">수량</th><th scope="col">금액</th><th scope="col">참조</th></tr></thead><tbody>'
      + items.map(it => {
        if (it.fut) return futDayHTML(it.fut, 'tr');
        const e = it.e, g = it.grp;
        if (!g) return '<tr data-n="' + it.n + '">' + cell(e, '<td class="l"><div class="ell" style="max-width:420px" title="' + esc(evDT(e)) + '">' + evDH(e) + (it.pay ? payChip(it.pay) : '') + '</div></td><td class="num nowrap">' + esc(evQ(e)) + '</td><td class="num nowrap">' + evA(e) + '</td>' + txc(e)) + '</tr>';
        const open = S.dayGrpOpen && S.dayGrpOpen.has(it.gk);
        return '<tr class="evgrp" data-n="' + it.n + '">' + cell(e, '<td class="l"><button class="link gtog" data-a="dayGrp" data-v="' + esc(it.gk) + '" aria-expanded="' + !!open + '">' + g.length + '건 체결 · ' + (open ? '접기' : '펼치기') + '</button> <span class="t2">' + esc(hs(e.d)) + '</span></td><td class="num nowrap"><b>' + (it.q != null ? (evXf(e) ? pvW(PVM.q) : q(it.q)) : '—') + '</b></td><td class="num nowrap"><b>' + (it.a != null ? (evXf(e) ? esc(pvMoney('', false)) : m(KV(it.a, it.aK))) : '—') + '</b></td><td class="tx num nowrap mut">' + g.length + '건</td>') + '</tr>'
          + (open ? g.map(x => '<tr class="evsub" data-n="0"><td class="l mut num nowrap">' + esc(String(x.t).slice(6)) + '</td><td class="l"></td><td class="l"></td><td class="l"><div class="ell" style="max-width:420px">' + esc(hs(x.d)) + '</div></td><td class="num nowrap">' + esc(evQ(x)) + '</td><td class="num nowrap">' + evA(x) + '</td>' + txc(x) + '</tr>').join('') : '');
      }).join('') + '</tbody></table></div>';
  }
  const evVenue = e => { const h = String(e.d || '').split(' · ')[0].trim(), sk = String(e.src || '');
    if (/^(거래소|온체인)|LP|유동성/.test(e.k) && h && h.length <= 16 && !/[→(]/.test(h)) return h;
    if (/^(거래소|입금 확인)/.test(e.k) && sk.indexOf('ex:') === 0) return EX_NAMES[sk.slice(3)] || sk.slice(3);
    return ''; };
  const evHM = e => String(e.t || '').slice(6);
  function dayBundles(evs) {
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const buys = new Set();
    evs.forEach(e => { if (e.k === '온체인 매수' && e.tx && /지불/.test(String(e.d || ''))) buys.add(payKey(e)); });
    const by = new Map(), pay = [];
    evs.forEach(e => {
      if (e.k === '온체인 매도' && e.tx && buys.has(payKey(e))) { pay.push(e); return; }
      const nm = String(evNm(e)).replace(/\s+#\d+$/, ''), key = e.k + '|' + nm;
      let b = by.get(key); if (!b) { b = { key, k: e.k, nm, e, evs: [] }; by.set(key, b); }
      b.evs.push(e);
    });
    const fin = b => {
      const as = b.evs.map(e => /\$/.test(String(e.a || '')) ? evNum(e.a) : NaN).filter(isFinite);
      b.usd = as.length ? sum(as) : null; b.krw = as.length ? evAK(b.evs) : null;
      const vs = new Map(); b.evs.forEach(e => { const v = evVenue(e) || ''; const x = vs.get(v) || { v, n: 0, usd: 0, has: false, evs: [] }; x.n++; const a = /\$/.test(String(e.a || '')) ? evNum(e.a) : NaN; if (isFinite(a)) { x.usd += a; x.has = true; x.evs.push(e); } vs.set(v, x); });
      vs.forEach(x => { x.krw = x.has ? evAK(x.evs) : null; });
      b.venues = [...vs.values()].sort((x, y) => (y.usd - x.usd) || (y.n - x.n));
      const ts = b.evs.map(evHM).filter(Boolean).sort(); b.t0 = ts[0] || ''; b.t1 = ts[ts.length - 1] || '';
      b.cat = b.pay ? 3 : /매도/.test(b.k) ? 0 : /매수/.test(b.k) ? 1 : 2;
      return b;
    };
    const out = [...by.values()].map(fin);
    if (pay.length) { const syms = [...new Set(pay.map(e => String(e.sym || '?')))]; out.push(fin({ key: '#pay', k: '스왑 지불', nm: syms.slice(0, 3).join(' · ') + (syms.length > 3 ? ' 외 ' + (syms.length - 3) + '종' : ''), pay: true, e: pay[0], evs: pay })); }
    out.sort((x, y) => (x.cat - y.cat) || (x.cat < 2 ? num(y.usd) - num(x.usd) : 0) || (y.evs.length - x.evs.length));
    return out;
  }
  function bundleHTML(b, iso, realBy, ux) {
    const open = S.dayBOpen && S.dayBOpen.has(b.key), each = open && ((S.dayBEach && S.dayBEach.has(b.key)) || b.evs.some(e => e.of || e.ofc));
    const nv = b.venues.filter(v => v.v).length;
    const ct = b.evs.length + '건' + (nv > 1 ? ' · ' + nv + (/거래소/.test(b.k) ? '거래소' : /온체인/.test(b.k) ? '체인' : '곳') : '');
    const vtxt = b.pay ? '매수할 때 낸 코인 · 손익 영향 작음' : b.venues.filter(v => v.v).slice(0, 3).map(v => v.v).join(' · ') + (nv > 3 ? ' 외 ' + (nv - 3) + '곳' : '');
    const tr = b.t0 ? (b.t0 === b.t1 ? b.t0 : b.t0 + '–' + b.t1) : '';
    const rz = !b.pay && (/매도/.test(b.k) || CONV_K.test(b.k)) && realBy ? realBy.get(String(b.e.sym || '').toUpperCase()) : null;
    const rzB = rz && !rz.used ? (rz.used = true, '<button class="link brz num ' + clsV(KV(rz.v, rz.vk)) + '" data-a="receipt" data-v="' + esc(iso + '|' + rz.sym) + '" title="' + esc(rz.sym) + ' 차익 영수증">실현 ' + m(KV(rz.v, rz.vk), { sign: true, compact: true }) + IC.right + '</button>') : '';
    const kc = b.pay ? '<span class="pill g sm">스왑 지불</span>' : evPill(b.k);
    return '<div class="bn' + (open ? ' open' : '') + (rzB ? ' hasrz' : '') + '" data-n="' + b.evs.length + '"><button class="bh" data-a="dayB" data-v="' + esc(b.key) + '" aria-expanded="' + !!open + '">'
      + '<span class="l1">' + kc + '<b class="sy ell">' + esc(b.nm) + '</b>' + (b.pay ? '' : impChip(b.e)) + '<span class="ct num">' + ct + '</span><b class="am num' + (b.pay ? ' mut' : '') + '">' + (b.usd != null ? m(KV(b.usd, b.krw != null ? b.krw : ux ? b.usd * ux : null), { compact: true }) : '—') + '</b></span>'
      + '<span class="l2 num"><span class="ell">' + esc([vtxt, tr].filter(Boolean).join(' · ')) + '</span>' + (rzB ? '' : IC.chev.replace('<svg', '<svg class="cv' + (open ? ' o' : '') + '" width="14" height="14"')) + '</span></button>' + rzB
      + (open ? '<div class="bx num">' + (b.venues.length > 1 ? b.venues.map(v => '<div class="row"><span>' + esc(v.v || '기타') + ' ' + v.n + '건</span><span class="sp"></span><span>' + (v.has ? m(KV(v.usd, v.krw != null ? v.krw : ux ? v.usd * ux : null), { compact: true }) : '—') + '</span></div>').join('') : '')
        + (each ? dayRowsHTML(groupDayEvs(b.evs)) : '<button class="link" data-a="dayBEach" data-v="' + esc(b.key) + '">' + b.evs.length + '건 낱개로 보기' + IC.right + '</button>') + '</div>' : '') + '</div>';
  }
  const lpPair = s => String(s == null ? '' : s).replace(/\s+#\d+$/, '').replace(/\s*\/\s*/g, '/');
  const coinKeyOf = e => e.lp ? 'LP:' + lpPair(evNm(e)) : String(e.sym || '?').toUpperCase();
  function dayCoins(evs, iso) {
    const payKey = e => (e.src || '') + '|' + (e.tx || '');
    const buys = new Map();
    evs.forEach(e => { if (e.k === '온체인 매수' && e.tx && /지불/.test(String(e.d || ''))) buys.set(payKey(e), e); });
    const kOf = new Map(), pay = new Set(), by = new Map();
    evs.forEach(e => {
      const pb = e.k === '온체인 매도' && e.tx ? buys.get(payKey(e)) : null, o = pb || e, key = coinKeyOf(o);
      if (pb) pay.add(e);
      kOf.set(e, key);
      let c = by.get(key); if (!c) { c = { key, lp: !!o.lp, e: o, n: 0, v: 0, vk: 0, vkOk: true, hasV: false }; by.set(key, c); }
      c.n++;
    });
    dayContrib(iso).forEach(x => {
      if (x.fut || x.gas || x.stk) return;
      const c = by.get(x.lp ? 'LP:' + lpPair(x.pool || x.sym) : String(x.sym).toUpperCase()); if (!c) return;
      c.v += x.v; c.hasV = true; if (x.vk == null) c.vkOk = false; else c.vk += num(x.vk);
    });
    const list = [...by.values()];
    list.forEach(c => { c.nm = c.lp ? lpPair(evNm(c.e)) : String(evNm(c.e)); });
    list.sort((a, b) => (Math.abs(b.v) - Math.abs(a.v)) || (b.n - a.n) || a.nm.localeCompare(b.nm));
    return { list, kOf, pay, by };
  }
  const coinIc = c => { if (!c.lp) return icon(c.e.sym, 'xs');
    const ps = c.nm.split('/'); return ps.length === 2 ? '<span class="pair">' + icon(ps[0], 'xs') + icon(ps[1], 'xs') + '</span>' : icon(c.nm, 'xs'); };
  const coinRz = c => KV(c.v, c.vkOk ? c.vk : null);
  const CONV_K = /^(스테이블 교환|원화 환전)$/;
  function dayPickSum(evs, C, keys, k) {
    const D = S.D, ux = k !== D.todayKey && num((D.usdt[k] || {}).usdt) > 0 ? num(D.usdt[k].usdt) : null;
    const b = { n: 0, u: 0, w: 0, ak: 0 }, s = { n: 0, u: 0, w: 0, ak: 0 }, cv = { n: 0, u: 0, w: 0, ak: 0 };
    evs.forEach(e => {
      if (keys && !keys.has(C.kOf.get(e))) return;
      const x = /매수/.test(e.k) ? b : (/매도/.test(e.k) && !C.pay.has(e)) ? s : CONV_K.test(e.k) ? cv : null; if (!x) return;
      x.n++;
      const a = String(e.a || ''), qn = Math.abs(evNum(e.q));
      if (/\$/.test(a) && isFinite(evNum(a))) {
        x.u += Math.abs(evNum(a));
        if (x.ak != null) x.ak = e.aK != null && isFinite(e.aK) ? x.ak + Math.abs(num(e.aK)) : null;
      }
      else if (/₩/.test(a)) { const w = Math.abs(parseMoney(a)); if (isFinite(w)) x.w += w; }
      else if (num(e.un) > 0 && isFinite(qn)) { x.u += num(e.un) * qn; x.ak = null; }
    });
    const val = x => KV(x.u + x.w / (ux || rate()), x.ak != null ? x.ak + x.w : ux ? x.u * ux + x.w : null);
    let rz;
    if (keys) { const cs = C.list.filter(c => keys.has(c.key) && c.hasV); rz = cs.length ? KV(sum(cs, c => c.v), cs.every(c => c.vkOk) ? sum(cs, c => c.vk) : null) : null; }
    else { const r0 = num(D.realized[k]); rz = Math.abs(r0) >= 0.005 ? KV(r0, D.hasKrw ? D.realizedK[k] : null) : null; }
    return { b, s, cv, bv: b.n ? val(b) : null, sv: s.n ? val(s) : null, cvv: cv.n ? val(cv) : null, rz };
  }
  function dayPickHTML(C, keys, sm, mob) {
    const L = C.list, sel = c => !!keys && keys.has(c.key);
    const nm = c => '<b>' + esc(c.nm) + '</b>' + (c.lp ? '<span class="lpt">LP</span>' : '');
    const rzT = c => c.hasV ? ' · 그날 실현 ' + m(coinRz(c), { sign: true }) : '';
    const chip = c => '<button class="dpc" data-a="dayPick" data-v="' + esc(c.key) + '" aria-pressed="' + sel(c) + '" title="' + esc(c.nm + (c.lp ? ' LP' : '') + ' · 그날 기록 ' + c.n + '건' + rzT(c)) + '"><span class="pl">' + coinIc(c) + nm(c) + '<span class="n num">' + c.n + '</span></span></button>';
    const q0 = String(S.drafts.dpq || '').trim().toLowerCase(), hit = c => !q0 || c.nm.toLowerCase().indexOf(q0) >= 0;
    const pop = S.pop === 'dpk' ? popBox('코인 고르기', '<label class="search dps">' + IC.search + '<input class="field" type="search" placeholder="코인 이름 찾기" data-draft="dpq" data-input="dpq" aria-label="코인 이름 찾기" autocomplete="off" spellcheck="false"></label>'
      + '<div class="scroll dpl" role="group" aria-label="그날 코인 ' + L.length + '종">' + L.map(c => '<button class="opt dpo' + (sel(c) ? ' on' : '') + '" data-a="dayPick" data-v="' + esc(c.key) + '" aria-pressed="' + sel(c) + '" data-q="' + esc(c.nm.toLowerCase()) + '"' + (hit(c) ? '' : ' hidden') + '>'
        + coinIc(c) + '<span class="nm ell">' + nm(c) + '</span><span class="n num">' + c.n + '건</span><span class="sp"></span>' + (c.hasV ? '<span class="rz num ' + clsV(coinRz(c)) + '">' + m(coinRz(c), { sign: true, compact: true }) + '</span>' : '') + optCk + '</button>').join('')
        + '<div class="dpe cap"' + (L.some(hit) ? ' hidden' : '') + '>맞는 코인이 없어요</div></div>'
        + '<div class="sep"></div><div class="row dpft"><span class="cap num">' + L.length + '종 · ' + (keys ? keys.size + '개 고름' : '전체') + '</span><span class="sp"></span><button class="link" data-a="dayPickAll">전체 보기</button></div>', 'dpkpop') : '';
    const more = '<div class="popw dpmore"><button class="dpc dpx" data-a="pop" data-v="dpk" aria-haspopup="dialog" aria-expanded="' + (S.pop === 'dpk') + '" aria-label="코인 찾기 · 그날 ' + L.length + '종">'
      + '<span class="pl">' + (mob ? IC.search.replace('<svg', '<svg width="16" height="16"') : '<span class="mn num">+' + L.length + '</span>') + '</span></button>' + pop + '</div>';
    const all = '<button class="dpc all" data-a="dayPickAll" aria-pressed="' + !keys + '" title="그날 기록 전체"><span class="pl">전체<span class="n num">' + sum(L, c => c.n) + '</span></span></button>';
    const rowH = '<div class="dpk' + (mob ? ' m' : '') + '" role="group" aria-label="코인 고르기"><div class="dpr">' + all + L.map(chip).join('') + '</div>' + more + '</div>';
    const who = keys ? (L.filter(sel).map(c => c.nm + (c.lp ? ' LP' : '')).join(' · ') || [...keys].join(' · ')) : '', nSel = keys ? sum(L.filter(sel), c => c.n) : 0;
    const st = (l, v, c9) => '<span class="st"><span class="l">' + l + '</span><b class="num' + (c9 ? ' ' + c9 : '') + '">' + v + '</b></span>';
    const sumH = '<div class="dpsum' + (keys ? ' on' : '') + (sm.cv && sm.cv.n ? ' c4' : '') + '">' + (mob ? '' : '<span class="who"><span class="ell" title="' + esc(who) + '">' + (keys ? esc(who) : '그날 전체') + '</span><span class="mut num">' + (keys ? nSel + '건' : L.length + '종') + '</span></span>')
      + st('매수 <span class="num">' + sm.b.n + '건</span>', sm.bv != null ? m(sm.bv, { compact: true }) : '—', sm.bv != null ? '' : 'mut')
      + st('매도 <span class="num">' + sm.s.n + '건</span>', sm.sv != null ? m(sm.sv, { compact: true }) : '—', sm.sv != null ? '' : 'mut')
      + (sm.cv && sm.cv.n ? st('<span title="스테이블 교환·원화 환전 — 세금상 처분이라 그날 실현에 들어가요">교환</span> <span class="num">' + sm.cv.n + '건</span>', sm.cvv != null ? m(sm.cvv, { compact: true }) : '—', sm.cvv != null ? '' : 'mut') : '')
      + st('실현', sm.rz != null ? m(sm.rz, { sign: true, compact: true }) : '—', sm.rz != null ? cls(sm.rz) : 'mut') + '</div>';
    return { row: rowH, sum: sumH };
  }
  function fitDayPick() {
    const dpk = document.querySelector('#dayEv .dpk'); if (!dpk) return;
    const row = dpk.querySelector('.dpr'), more = dpk.querySelector('.dpmore'), btn = more && more.querySelector('.dpc.dpx');
    if (!row || !btn) return;
    if (dpk.classList.contains('m')) { dpFade(row); return; }
    const chips = [...row.querySelectorAll('.dpc[data-a=dayPick]')];
    chips.forEach(c => { c.hidden = false; }); more.hidden = false;
    const gap = parseFloat(getComputedStyle(row).columnGap) || 6;
    const avail = dpk.clientWidth;
    if (row.scrollWidth <= avail - more.offsetWidth - gap && S.pop !== 'dpk') { more.hidden = true; return; }
    const allW = row.firstElementChild ? row.firstElementChild.offsetWidth : 0;
    const mn = btn.querySelector('.mn');
    const lab = (n, ns) => { if (mn) mn.textContent = n ? '+' + n + (ns ? ' · 고름 ' + ns : '') : '찾기'; };
    const w = chips.map(c => c.offsetWidth + gap);
    const on = chips.map(c => c.getAttribute('aria-pressed') === 'true');
    const pick = budget => { const keep = new Set(); let used = allW;
      chips.forEach((c, i) => { if (on[i] && used + w[i] <= budget) { keep.add(i); used += w[i]; } });
      chips.forEach((c, i) => { if (!on[i] && !keep.has(i) && used + w[i] <= budget) { keep.add(i); used += w[i]; } else if (!on[i] && !keep.has(i)) used = Infinity; });
      return keep; };
    let keep = new Set(chips.map((c, i) => i));
    for (let t = 0; t < 3; t++) {
      const hid = chips.length - keep.size, hs0 = chips.filter((c, i) => on[i] && !keep.has(i)).length;
      lab(hid, hs0);
      keep = pick(avail - btn.offsetWidth - gap);
    }
    chips.forEach((c, i) => { c.hidden = !keep.has(i); });
    const hid = chips.length - keep.size, hs0 = chips.filter((c, i) => on[i] && !keep.has(i)).length;
    lab(hid, hs0);
    btn.setAttribute('aria-label', '코인 ' + (hid ? hid + '개 더 보기 · 찾기' : '찾기') + (hs0 ? ' · 고른 코인 ' + hs0 + '개 숨음' : ''));
    if (!hid && S.pop !== 'dpk') more.hidden = true;
    if (!more.hidden) more.classList.toggle('rt', more.getBoundingClientRect().left + 360 > document.documentElement.clientWidth - 16);
  }
  function dpFilter(v) {
    const q0 = String(v || '').trim().toLowerCase(), pop = document.querySelector('.pop.dpkpop'); if (!pop) return;
    let any = false;
    pop.querySelectorAll('.dpo').forEach(o => { const ok = !q0 || String(o.getAttribute('data-q') || '').indexOf(q0) >= 0; o.hidden = !ok; if (ok) any = true; });
    const e = pop.querySelector('.dpe'); if (e) e.hidden = any;
  }
  function dayPickKey(ev, t) {
    const k = ev.key, vis = els => els.filter(x => !x.hidden && x.offsetParent !== null);
    const pop = t.closest('.pop.dpkpop');
    if (pop) {
      const items = vis([pop.querySelector('input')].concat([...pop.querySelectorAll('.dpo')]).filter(Boolean));
      const i = items.indexOf(t);
      if (k === 'ArrowDown' || k === 'ArrowUp') { ev.preventDefault(); const n = items[Math.max(0, Math.min(items.length - 1, i + (k === 'ArrowDown' ? 1 : -1)))]; if (n) n.focus(); return true; }
      if (k === 'Enter' && t.tagName === 'INPUT') { ev.preventDefault(); const f = items.find(x => x.classList.contains('dpo')); if (f) A.dayPick(f); return true; }
      return false;
    }
    if ((k === 'ArrowRight' || k === 'ArrowLeft') && t.classList.contains('dpc') && t.closest('#dayEv .dpk')) {
      const items = vis([...t.closest('.dpk').querySelectorAll('.dpc')]), i = items.indexOf(t);
      const n = items[i + (k === 'ArrowRight' ? 1 : -1)]; if (n) { ev.preventDefault(); n.focus(); n.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
      return true;
    }
    return false;
  }
  function dpFocusKey() {
    const ae = document.activeElement; if (!ae || !ae.closest) return null;
    const inPop = !!ae.closest('.pop.dpkpop'); if (!inPop && !ae.closest('#dayEv .dpk')) return null;
    return { pop: inPop, input: ae.tagName === 'INPUT', a: ae.getAttribute('data-a'), v: ae.getAttribute('data-v'), pos: ae.tagName === 'INPUT' ? ae.selectionStart : null };
  }
  function dpRefocus(f) {
    const ce = x => window.CSS && CSS.escape ? CSS.escape(x) : x;
    const n = f.input ? $('.pop.dpkpop input') : $((f.pop ? '.pop.dpkpop' : '#dayEv .dpk') + ' [data-a="' + ce(f.a || '') + '"]' + (f.v != null ? '[data-v="' + ce(f.v) + '"]' : ''));
    if (!n || n === document.activeElement) return;
    n.focus({ preventScroll: true });
    if (f.input && f.pos != null) { try { n.setSelectionRange(f.pos, f.pos); } catch (e) {  } }
  }
  const dpFade = row => { if (!row) return; const x = row.scrollLeft, mx = row.scrollWidth - row.clientWidth;
    row.classList.toggle('fl', x > 2); row.classList.toggle('fr', mx - x > 2); };
  function futDayLines(iso) {
    const fu = (S.D && S.D.fut) || {};
    if (!iso) return [];
    const ex = fu.realizedByDateEx;
    if (ex && typeof ex === 'object' && !Array.isArray(ex)) return arr(ex[iso]).filter(x => x && isFinite(+x.usd) && Math.abs(+x.usd) >= 0.005 && srcPass({ src: 'ex:' + String(x.exKey || '') }))
      .map(x => ({ ex: String(x.ex || x.exKey || ''), usd: +x.usd, krw: x.krw != null && isFinite(+x.krw) ? +x.krw : null, n: Math.max(0, Math.floor(num(x.n))), t: /^\d\d:\d\d$/.test(String(x.t || '')) ? String(x.t) : '', ts: num(x.ts) > 0 ? num(x.ts) : 0, iso, exKey: String(x.exKey || '') }));
    const u = num((fu.realizedByDate || {})[iso]), k = (fu.realizedKrwByDate || {})[iso];
    if (Math.abs(u) < 0.005 || S.src.mode !== 'all') return [];
    return [{ ex: '', usd: u, krw: k != null && isFinite(+k) ? +k : null, n: 0, t: '', iso, exKey: '' }];
  }
  function futDayHTML(x, mode) {
    const v = KV(x.usd, x.krw), alt = S.cur === 'USD' ? mAlt(x.krw != null ? x.krw / rate() : x.usd, { sign: true, compact: mode === 'bn' }) : mAlt(x.usd, { sign: true, compact: mode === 'bn' });
    const nm = esc(x.ex || '선물'), ct = x.n ? '<span class="pvx">' + x.n + '건</span>' : '', tip = ' title="' + esc('선물 정산' + (x.ex ? ' · ' + x.ex : '') + ' — 정산 + 수수료 + 펀딩 · 누르면 선물 영수증') + '"';
    const fa = x.iso ? 'data-a="futRcpt" data-fv="' + esc(x.iso + '|' + (x.exKey || '')) + '"' : 'data-a="openFut"';
    const amt = '<b class="num ' + clsV(v) + '">' + m(v, { sign: true, compact: mode === 'bn' }) + '</b>';
    const FUT_CV = IC.right.replace('<svg', '<svg class="cv" width="14" height="14"');
    if (mode === 'bn') return '<div class="bn futd" data-n="0"><button class="bh" ' + fa + tip + '><span class="l1">' + evPill('선물 정산') + '<b class="sy ell">' + nm + '</b>' + (ct ? '<span class="ct num">' + ct + '</span>' : '') + '<b class="am num ' + clsV(v) + '">' + m(v, { sign: true, compact: true }) + '</b></span>'
      + '<span class="l2 num"><span class="ell">' + esc(x.t) + '</span><span>' + alt + '</span>' + FUT_CV + '</span></button></div>';
    if (mode === 'div') return '<div class="futd" data-n="0" ' + fa + ' role="button" tabindex="0"' + tip + '><div class="row gap8">' + evPill('선물 정산') + '<b>' + nm + '</b>' + (ct ? ' <span class="mut num">' + ct + '</span>' : '') + '<span class="sp"></span><span class="mut num ftm">' + esc(x.t) + '</span></div>'
      + '<div class="row sub num"><span class="sp"></span><span class="fam">' + amt + '<div class="mut">' + alt + '</div></span></div></div>';
    return '<tr class="clk futd" data-n="0" ' + fa + ' role="button" tabindex="0"' + tip + '><td class="l mut num nowrap">' + esc(x.t) + '</td><td class="l">' + evPill('선물 정산') + '</td><td class="l"><b>' + nm + '</b></td><td class="l"><span class="t2">' + ct + '</span></td><td class="num nowrap">—</td>'
      + '<td class="num nowrap">' + amt + '<div class="sub num">' + alt + '</div></td><td class="tx num nowrap mut">' + FUT_CV + '</td></tr>';
  }
  function dayEventsHTML() {
    const D = S.D, k = S.day || D.todayKey;
    const evs0 = (dayFull(k) || D.evByDay.get(k) || []).filter(srcPass);
    let evs = evs0;
    const full = dayFull(k), cn = dayCnt(k);
    if (dayWait(k) && (!cn || cn.n > 0)) return '<div class="card' + (S.mobile || S.narrow ? ' dayev m' : '') + '" id="dayEv"' + (S.mobile || S.narrow ? '' : ' style="margin-top:20px"') + ' aria-busy="true"><div class="tblhead"><h2 class="h2">그날의 기록</h2><span class="sp"></span><span class="cap num" role="status" aria-live="polite">'
      + esc((+k.slice(0, 2)) + '/' + (+k.slice(3, 5))) + (cn ? ' · ' + cn.n + '건' : '') + ' · 전체 기록 받는 중</span></div>' + evSkel(Math.min(8, Math.max(3, cn ? cn.n : 5)), 0) + '</div>';
    const fRe = !!(full && ((S.dayFull || {})[isoDay(k)] || {}).st === 'load');
    const C = dayCoins(evs0, isoDay(k));
    let fs = S.daySym && S.daySym.keys && S.daySym.keys.size ? S.daySym : null;
    if (fs && (full || fs.k === k)) {
      const have = S.src.mode === 'all' || !full ? C.by : dayCoins(full, isoDay(k)).by;
      const ks = [...fs.keys].filter(x => have.has(x));
      if (full && !ks.length) fs = S.daySym = null;
      else if (full && (fs.k !== k || ks.length !== fs.keys.size)) fs = S.daySym = { k, keys: new Set(ks) };
    }
    const keys = fs ? fs.keys : null;
    if (keys) evs = evs0.filter(e => keys.has(C.kOf.get(e)));
    const mob = S.mobile, PK = C.list.length ? dayPickHTML(C, keys, dayPickSum(evs0, C, keys, k), mob) : null;
    const fl = keys ? [] : futDayLines(isoDay(k));
    const nAll = keys ? evs.length : (cn ? Math.max(cn.n, evs.length) : evs.length), part = !full && (keys ? false : nAll > evs.length);
    const fc = S.dayFull && S.dayFull[isoDay(k)], err = !full && !!fc && fc.st === 'err';
    const partTxt = part ? (err ? '전체 기록을 못 불러왔어요 · 최근 ' + evs.length + '건만 표시' : '전체 기록 불러오는 중') : (err ? '전체 기록을 못 불러왔어요 · 요약 데이터로 표시 중' : '');
    const retry = err ? '<button class="btn sm" data-a="dayRetry" data-v="' + esc(isoDay(k)) + '">' + IC.undo + ' 다시 시도</button>' : '';
    const empty = part ? '<div class="empty"><div class="eic">' + IC.cal + '</div><b>' + esc(partTxt) + '</b>' + (err ? '<button class="btn sm" data-a="dayRetry" data-v="' + esc(isoDay(k)) + '" style="margin-top:10px">다시 시도</button>' : '') + '</div>'
      : '<div class="empty"><div class="eic">' + IC.cal + '</div><b>기록된 거래가 없어요</b>' + (S.src.mode !== 'all' ? '소스 필터가 적용되어 있어요' : '다른 날짜를 눌러 보세요') + '</div>';
    if ((S.mobile || S.narrow) && S.dayView !== 'each') {
      const bs = dayBundles(evs), bk = 'dayb:' + k + (keys ? ':' + [...keys].join(',') : '');
      const iso = isoDay(k), realBy = new Map(), ux = k !== D.todayKey && num((D.usdt[k] || {}).usdt) > 0 ? num(D.usdt[k].usdt) : null;
      dayContrib(iso).filter(rcptable).forEach(x => { const u0 = String(x.sym).toUpperCase(); if (!realBy.has(u0)) realBy.set(u0, { sym: x.sym, v: x.v, vk: x.vk }); });
      return '<div class="card dayev m" id="dayEv"><div class="tblhead"><h2 class="h2">그날의 기록</h2><span class="sp"></span><span class="cap num' + (err ? ' wtxt' : '') + '">' + esc((+k.slice(0, 2)) + '/' + (+k.slice(3, 5))) + ' · ' + nAll + '건' + (bs.length && evs.length ? ' → ' + bs.length + '묶음' : '') + (partTxt ? ' · ' + partTxt : '') + '</span>' + (fRe ? rfrTag() : '') + '</div>'
        + (PK ? PK.row + PK.sum : '') + '<div class="dvbar">' + srcBtn() + '<div class="seg" role="group" aria-label="보기 방식"><button data-a="dayView" data-v="grp" class="on" aria-pressed="true">묶음</button><button data-a="dayView" data-v="each" aria-pressed="false">낱개</button></div>' + retry + '</div>'
        + (evs.length || fl.length ? '<div class="bns">' + fl.map(x => futDayHTML(x, 'bn')).join('') + (evs.length ? uiPaged(bk, bs, b => bundleHTML(b, iso, realBy, ux), { unit: '묶음' }) : '') + '</div>' : empty) + '</div>';
    }
    const itemsE = groupDayEvs(evs), items = futMerge(itemsE, fl, isoDay(k));
    const rk = 'dayr:' + k + (keys ? ':' + [...keys].join(',') : ''), pgD = uiPgSlice(rk, items), rows = pgD.rows;
    const items0 = keys ? groupDayEvs(evs0) : itemsE, nHead = keys ? (cn ? Math.max(cn.n, evs0.length) : evs0.length) : nAll;
    const packed = items0.length < (keys ? evs0 : evs).length ? ' · ' + items0.length + '줄로 묶음' : '';
    const viewSeg = S.mobile || S.narrow ? '<div class="seg" role="group" aria-label="보기 방식"><button data-a="dayView" data-v="grp" aria-pressed="false">묶음</button><button data-a="dayView" data-v="each" class="on" aria-pressed="true">낱개</button></div>' : '';
    return '<div class="card" id="dayEv" style="margin-top:20px"><div class="tblhead"><h2 class="h2">그날의 기록</h2><span class="cap num' + (err ? ' wtxt' : '') + '">' + (mob ? nAll : nHead) + '건 · ' + esc(isoDay(k) || k) + (partTxt ? ' · ' + partTxt : packed) + '</span>' + (fRe ? rfrTag() : '') + (PK && !mob ? PK.row : '') + retry + '<div class="sp"></div>' + viewSeg + srcBtn() + '</div>'
      + (PK ? (mob ? PK.row : '') + PK.sum : '')
      + (evs.length || fl.length ? (pgD.last > 0 ? '<div class="upga" data-pga="' + esc(rk) + '"></div>' : '') + dayRowsHTML(rows) + uiPgBar(rk, items.length, { unit: '줄' })
        : empty) + '</div>';
  }
  const apOf = d => !!d && d.date !== S.D.todayKey && num(d.ap) > 0;
  const apTxt = d => '근사 — 그날 시세 기록 없는 자산 ' + m(num(d.est), { compact: true }) + '은 추정 시세' + (num(d.xc) > 0 ? ', 원장 밖 잔고 ' + m(num(d.xc), { compact: true }) + '은 지금 값 이월' : '') + '로 평가';
  const apTitle = d => apOf(d) ? ' title="' + esc(apTxt(d)) + '"' : '';
  function recentHTML(inner) {
    const D = S.D;
    const days = D.daily.slice().reverse();
    if (!days.length) return inner ? '<div class="cap" style="padding:16px 0">일별 마감이 쌓이면 여기에 보여요</div>' : '';
    const dlt = d => (d.date === D.todayKey && D._today != null ? todayD() : (d._prev ? dayV(d) - dayV(d._prev) : null));
    const dval = d => (d.date === D.todayKey ? D.total : dayV(d));
    const spl = d => (d.date === D.todayKey ? !!D._todaySplit : !!d.split);
    const rbDayTxt = d => (d.rb ? ' · Rabby 기준 ' + m(num(d.rb), { sign: true }) + ' 포함' + (d.rbNew ? '(첫 반영 — 입출금으로 셈)' : '') : '');
    const summary = d => { const r = KV(num(D.realized[d.date]), D.hasKrw ? D.realizedK[d.date] : null), cn = dayCnt(d.date, true), s = cn ? cn.s : (D.evByDay.get(d.date) || []).filter(e => /매도/.test(e.k)).length, b = cn ? cn.b : 0;
      const iso = isoDay(d.date), fo = iso && Math.abs(num((D.f.realizedByDate || {})[iso])) < 0.005 && Math.abs(num((D.fut.realizedByDate || {})[iso])) >= 0.005;
      if (r && fo && !s) return '선물 ' + m(r, { sign: true, compact: true }) + (b ? ' · 매수 ' + b + '건' : '');
      const py = cn ? cn.pay : 0;
      return r || s ? (r ? '실현 ' + m(r, { sign: true, compact: true }) : '실현 없음') + (s || !py ? ' · 매도 ' + s + '건' : ' · 스왑 지불 ' + py + '건') : (b ? '실현 없음 · 매수 ' + b + '건' : '매매 없음'); };
    return (inner ? '<div class="rclist">' : '<div class="card" style="margin-top:20px"><div class="tblhead"><h2 class="h2">최근 ' + days.length + '일 마감</h2><span class="cap">USDT 종가·김프 포함 · 행을 누르면 그날로 이동</span></div>')
      + (S.mobile || S.narrow ? '<div class="m-list">' + uiPaged('rc30', days, d => { const u = D.usdt[d.date] || {}; const st = d.date === D.todayKey ? !!D._todayStep : D.steps.indexOf(d.date) >= 0; return '<button class="it" data-a="pickDay" data-v="' + esc(d.date) + '"><div><b class="num">' + esc(d.date) + '</b> <span class="mut">' + esc(d.dow || '') + '</span><div class="sub num">' + esc(summary(d)) + '</div></div><div class="r"><div class="val num"' + (d.rb ? ' title="' + esc(m(dval(d)) + (apOf(d) ? ' · ' + apTxt(d) : '') + rbDayTxt(d)) + '"' : apTitle(d)) + '>' + (apOf(d) ? '≈ ' : '') + m(dval(d), { compact: true }) + '</div><div class="num ' + (st || spl(d) ? 'mut' : cls(dlt(d))) + '" style="font-size:13px">' + (dlt(d) == null ? '—' : m(dlt(d), { sign: true, compact: true })) + (st || spl(d) ? ' · 입출금' : '') + '</div></div></button>'; }, { unit: '일' }) + '</div>'
        : '<table><thead><tr><th scope="col">날짜</th><th scope="col" class="l">요약</th><th scope="col">USDT 종가</th><th scope="col">김프</th><th scope="col">총자산</th><th scope="col">변동</th></tr></thead><tbody>' + uiPaged('rc30', days, d => {
          const u = D.usdt[d.date] || {}, kp = u.kimp != null ? num(u.kimp) : null, st = d.date === D.todayKey ? !!D._todayStep : D.steps.indexOf(d.date) >= 0;
          return '<tr class="clk' + (S.day === d.date ? ' open' : '') + '" data-a="pickDay" data-v="' + esc(d.date) + '" role="button" tabindex="0"><td class="num rcd" title="' + esc(isoDay(d.date) || d.date) + '"><span class="nowrap">' + esc(d.date) + '</span> <span class="mut nowrap">(' + esc(d.dow || '') + ')</span></td><td class="l"><span class="t2">' + summary(d).split(' · ').map(x => '<span class="nowrap">' + esc(x) + '</span>').join(' · ') + '</span>' + (isLLM(D.reviews[d.date]) ? ' <span class="tag-ai">AI 리뷰</span>' : '') + '</td><td class="num pvx">' + (u.usdt ? '₩' + nf('ko-KR').format(num(u.usdt)) : '—') + '</td><td class="num rck" style="color:' + kimpCol(kp) + '">' + (kp == null ? '—' : '<span class="nowrap">' + pctS(kp, 2) + '</span>' + (kp > 2 ? kimpChip(kp) : '')) + '</td><td class="num" title="' + esc(m(dval(d)) + (apOf(d) ? ' · ' + apTxt(d) : '') + rbDayTxt(d)) + '"><b>' + (apOf(d) ? '<span class="mut">≈ </span>' : '') + m(dval(d), { compact: true }) + '</b>' + (d.rbNew ? '<div class="sub">Rabby 기준 첫 반영</div>' : '') + '</td><td class="num ' + (st || spl(d) ? 'mut' : cls(dlt(d))) + '"' + (dlt(d) == null ? '' : ' title="' + esc(m(dlt(d), { sign: true }) + (attOf(d.date) ? ' — ' + attLine(attOf(d.date), 3, false) : '')) + '"') + '>' + (dlt(d) == null ? '—' : m(dlt(d), { sign: true, compact: true })) + (spl(d) && dlt(d) != null && (d.date === D.todayKey ? D._todayFlow : d.flow) != null ? (() => { const fl = d.date === D.todayKey ? num(D._todayFlow) : dayFlowV(d), mk = dlt(d) - fl;
            if (attOf(d.date)) return '<div class="sub rcsplit" title="' + esc(flowTip(fl, d.date === D.todayKey ? D._todayFlowTop : d.flowTop)) + '"><span class="rcp">입출금 <span class="nowrap">' + m(fl, { sign: true, compact: true }) + '</span></span></div>';
            return '<div class="sub rcsplit" title="' + esc(flowTip(fl, d.date === D.todayKey ? D._todayFlowTop : d.flowTop)) + '"><span class="rcp">시장 <span class="nowrap ' + cls(mk) + '">' + m(mk, { sign: true, compact: true }) + '</span></span> · <span class="rcp">입출금 <span class="nowrap">' + m(fl, { sign: true, compact: true }) + '</span></span></div>'; })() : (st ? '<div class="sub">입출금 포함</div>' : '')) + '</td></tr>';
        }, { tr: 6, unit: '일' }) + '</tbody></table>') + '</div>';
  }
  return {
    apOf, dayContrib, dayPickKey, DM_MAX, dmCoins, dmGet, dmInput, dmRcptHTML, dmSwapKeepForm, dmSym, dpFade, dpFilter, dpFocusKey, dpRefocus, feeRef,
    fitDayPick, groupDayEvs, isAI, isoAdd, monthAtt, monthBarRows, payChip, rcptable, realDays, vDaily, wkOff, wkSelNow, __late
  };
};
